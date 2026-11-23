<script setup>
import { onBeforeUnmount, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { ArrowLeft, Refresh } from "@element-plus/icons-vue";
import API from "@/components/api";
import { useUserStore } from "@/stores/userStore";
import { createPaymentClient, paymentsEnabled, paymentErrorMessage } from "@/services/paymentClient.mjs";
import { browserPaymentRecovery } from "@/services/paymentRecovery.mjs";

const route = useRoute();
const router = useRouter();
const paymentApi = createPaymentClient({ baseURL: import.meta.env.VITE_API_BASE || "" });
const recovery = browserPaymentRecovery();
const userStore = useUserStore();
const drafts = ref([]);
const selected = ref(null);
const loading = ref(false);
const submitting = ref(false);
const errorText = ref("");
const shipping = reactive({ recipientName: "", recipientPhone: "", recipientAddress: "" });
let epoch = 0;
let checkoutEpoch = 0;
const checkingOut = ref(false);
const label = (state) => ({
  PREPARED: "待核对", CONFIRMED: "已确认资料（未付款）", CANCELLED: "已取消", EXPIRED: "已过期",
}[state] || state);

async function refresh(id = route.query.id) {
  checkoutEpoch++;
  checkingOut.value = false;
  submitting.value = false;
  const ticket = ++epoch;
  const user = userStore.userId;
  loading.value = true;
  selected.value = null;
  errorText.value = "";
  Object.assign(shipping, { recipientName: "", recipientPhone: "", recipientAddress: "" });
  try {
    const list = await API.listDrafts(typeof route.query.requestKey === "string" ? route.query.requestKey : undefined);
    if (ticket !== epoch || user !== userStore.userId) return;
    drafts.value = list;
    if (!id && list.length) id = list[0].draftId;
    if (typeof id === "string" && id) {
      const current = await API.getDraft(id);
      if (ticket !== epoch || user !== userStore.userId) return;
      selected.value = current;
      Object.assign(shipping, {
        recipientName: current.recipientName || "", recipientPhone: current.recipientPhone || "",
        recipientAddress: current.recipientAddress || "",
      });
    }
  } catch (error) {
    if (ticket === epoch && user === userStore.userId) errorText.value = error.message || "草稿读取失败";
  } finally {
    if (ticket === epoch) loading.value = false;
  }
}

async function checkout() {
  if (checkingOut.value || submitting.value || !paymentsEnabled || selected.value?.status !== "CONFIRMED") return;
  const owner = { userId: userStore.userId, token: userStore.token };
  const draft = { ...selected.value };
  const ticket = ++checkoutEpoch;
  const current = () => ticket === checkoutEpoch && owner.token === userStore.token && owner.userId === userStore.userId && selected.value?.draftId === draft.draftId;
  checkingOut.value = true;
  errorText.value = "";
  try {
    const key = recovery.checkoutKey(owner.userId, draft.draftId, draft.version, () => crypto.randomUUID());
    const order = await paymentApi.checkout(draft.draftId, draft.version, key, owner);
    if (current()) await router.push(`/payment/${encodeURIComponent(order.orderId)}`);
  } catch (error) {
    if (current()) errorText.value = error.outcome === "UNKNOWN"
      ? "订单转换结果尚未确认；可先查看付款订单，或再次点击进入付款，系统沿用原请求键恢复，不会重复建单。"
      : paymentErrorMessage(error);
  } finally { if (current()) checkingOut.value = false; }
}

async function confirm() {
  if (submitting.value || !selected.value?.canConfirm) return;
  const data = { version: selected.value.version, recipientName: shipping.recipientName.trim(),
    recipientPhone: shipping.recipientPhone.trim(), recipientAddress: shipping.recipientAddress.trim() };
  if (!data.recipientName || data.recipientName.length > 15 || !/^1[3-9]\d{9}$/.test(data.recipientPhone)
    || !data.recipientAddress || data.recipientAddress.length > 50) {
    ElMessage.error("请填写有效收货人（最多15字）、手机号和地址（最多50字）");
    return;
  }
  const user = userStore.userId;
  const token = userStore.token;
  const ticket = epoch;
  const id = selected.value.draftId;
  submitting.value = true;
  try {
    const result = await API.confirmDraft(id, data);
    if (user !== userStore.userId || token !== userStore.token || ticket !== epoch) return;
    selected.value = result;
    drafts.value = drafts.value.map((draft) => draft.draftId === id ? result : draft);
    ElMessage.success("资料已确认，尚未付款；余额与库存未扣减");
  } catch (error) {
    if (user === userStore.userId && token === userStore.token && ticket === epoch) {
      ElMessage.error(error.message || "确认失败，请刷新核对");
      await refresh(id);
    }
  } finally {
    if (ticket === epoch) submitting.value = false;
  }
}

async function cancel() {
  if (submitting.value || selected.value?.status !== "PREPARED") return;
  const id = selected.value.draftId;
  const user = userStore.userId;
  const token = userStore.token;
  const ticket = epoch;
  submitting.value = true;
  try {
    const result = await API.cancelDraft(id, selected.value.version);
    if (user === userStore.userId && token === userStore.token && ticket === epoch) {
      selected.value = result;
      drafts.value = drafts.value.map((draft) => draft.draftId === id ? result : draft);
    }
  } catch (error) {
    if (user === userStore.userId && token === userStore.token && ticket === epoch) ElMessage.error(error.message || "取消失败，请刷新核对");
  } finally {
    if (ticket === epoch) submitting.value = false;
  }
}

async function revoke() {
  try {
    await API.revokeOrderAgent();
    ElMessage.success("后续订单准备授权已撤销，已保存草稿保留");
  } catch (error) {
    ElMessage.error(error.message || "撤销失败");
  }
}

watch(() => [route.query.id, route.query.requestKey, userStore.userId, userStore.token], () => {
  checkoutEpoch++;
  checkingOut.value = false;
  submitting.value = false;
  drafts.value = [];
  selected.value = null;
  Object.assign(shipping, { recipientName: "", recipientPhone: "", recipientAddress: "" });
  if (userStore.isLoggedIn) refresh();
  else epoch++;
}, { immediate: true, flush: "sync" });
onBeforeUnmount(() => { epoch++; checkoutEpoch++; });
</script>

<template>
  <main class="draft-page">
    <header class="draft-header">
      <div><h2>我的草稿</h2><p>核对商品与收货资料 · 确认后仍未付款</p></div>
      <div class="draft-actions">
        <RouterLink v-if="paymentsEnabled" to="/payments"><el-button plain>付款订单</el-button></RouterLink>
        <RouterLink to="/main"><el-button :icon="ArrowLeft" plain>返回对话</el-button></RouterLink>
        <el-button :icon="Refresh" :disabled="loading || submitting" @click="refresh(selected?.draftId)">刷新</el-button>
      </div>
    </header>
    <el-alert v-if="errorText" :title="errorText" type="error" show-icon :closable="false" />
    <div class="draft-layout" v-loading="loading">
      <aside class="draft-list">
        <h3>最近草稿 <span>{{ drafts.length }}</span></h3>
        <el-empty v-if="!drafts.length" description="暂无草稿" :image-size="55" />
        <button v-for="draft in drafts" :key="draft.draftId" :class="{ active: selected?.draftId === draft.draftId }"
          :disabled="loading || submitting" @click="refresh(draft.draftId)">
          <span class="draft-list-top"><span>{{ label(draft.status) }}</span><strong>¥{{ draft.totalPrice }}</strong></span>
          <small>{{ new Date(draft.createdAt * 1000).toLocaleString() }}</small>
        </button>
      </aside>
      <section v-if="selected" class="draft-detail">
        <div class="detail-heading"><h3>{{ label(selected.status) }}</h3><el-tag effect="plain" size="small">未付款 · 不占库存</el-tag></div>
        <p class="expiry">有效期至 {{ new Date(selected.expiresAt * 1000).toLocaleString() }}</p>
        <div class="item-list">
          <article v-for="item in selected.items" :key="item.medicineId" class="draft-product">
            <div><strong>{{ item.name }} <span>× {{ item.quantity }}</span></strong>
              <p>草稿单价 ¥{{ item.price }} · 当前单价 ¥{{ item.currentPrice }} · 库存 {{ item.currentStock }}</p>
              <p v-if="item.blockedReason" class="error">{{ item.blockedReason }}</p>
            </div>
          </article>
        </div>
        <div class="draft-total"><span>草稿金额</span><strong>¥{{ selected.totalPrice }}</strong></div>
        <p v-if="selected.currentTotal !== selected.totalPrice" class="current-total">当前商品合计 ¥{{ selected.currentTotal }}，请重新核对。</p>
        <el-alert v-if="selected.blockingReasons?.length" type="warning" :closable="false" show-icon
          title="当前暂不能确认，请回到对话重新查询并准备草稿">
          <p v-for="reason in selected.blockingReasons" :key="reason">{{ reason }}</p>
        </el-alert>
        <form class="shipping-form" @submit.prevent="confirm">
          <h3>收货资料</h3>
          <p v-if="selected.shippingPrefilled" class="privacy-note">已从你的个人资料预填，请核对后确认。</p>
          <p class="privacy-note">仅用于业务核对，不发送给AI。此操作不扣款、不代表成交。</p>
          <div class="shipping-grid">
            <label>收货人<el-input v-model="shipping.recipientName" maxlength="15" placeholder="请输入收货人"
              :disabled="selected.status !== 'PREPARED' || submitting" /></label>
            <label>手机号<el-input v-model="shipping.recipientPhone" maxlength="11" inputmode="tel" placeholder="请输入手机号"
              :disabled="selected.status !== 'PREPARED' || submitting" /></label>
          </div>
          <label>收货地址<el-input v-model="shipping.recipientAddress" maxlength="50" placeholder="请输入收货地址"
            :disabled="selected.status !== 'PREPARED' || submitting" /></label>
          <div class="confirm-actions">
            <el-button type="primary" native-type="submit" :loading="submitting" :disabled="!selected.canConfirm || loading">确认资料（不付款）</el-button>
            <el-button :disabled="selected.status !== 'PREPARED' || submitting || loading" @click="cancel">取消草稿</el-button>
          </div>
        </form>
        <div v-if="selected.status === 'CONFIRMED'" class="checkout-entry">
          <p>{{ paymentsEnabled ? '资料已确认。下一步创建待支付订单，再独立验证与付款；此按钮不扣款。' : '本环境尚未启用独立付款，已确认草稿会保留。' }}</p>
          <el-button v-if="paymentsEnabled" type="primary" :loading="checkingOut" :disabled="loading || submitting" @click="checkout">进入独立付款（不扣款）</el-button>
        </div>
        <details class="draft-meta"><summary>草稿信息</summary>
          <p>草稿号：{{ selected.draftId }}</p><p>请求键：{{ selected.requestKey }} · 版本 {{ selected.version }}</p>
        </details>
      </section>
      <section v-else class="draft-empty"><el-empty description="从对话中的商品清单开始准备草稿" :image-size="90" /></section>
    </div>
    <footer class="draft-footer"><span>准备中断后，可在此恢复已保存的草稿。</span><el-button link type="danger" @click="revoke">撤销订单准备授权</el-button></footer>
  </main>
</template>

<style scoped>
.draft-page { max-width: 1080px; margin: 0 auto; padding: 24px; line-height: 1.7; }
.draft-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 20px; }
.draft-header h2 { margin: 0 0 4px; font-size: 20px; font-weight: 500; }
.draft-header p { margin: 0; color: #909399; font-size: 12px; }
.draft-actions { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }
.draft-layout { display: grid; grid-template-columns: 230px minmax(0, 1fr); gap: 18px; min-height: 300px; margin-top: 16px; align-items: start; }
.draft-list { padding: 12px; background: #fff; border: 1px solid #e4e7ed; border-radius: 6px; }
.draft-list h3 { font-size: 13px; color: #606266; margin: 0 0 12px; font-weight: 500; }
.draft-list h3 > span { color: #909399; font-weight: normal; margin-left: 6px; }
.draft-list button { display: block; width: 100%; border: 0; border-radius: 4px; background: transparent; padding: 10px; text-align: left; cursor: pointer; color: #606266; margin-bottom: 4px; }
.draft-list button:hover { background: #f5f7fa; }
.draft-list button.active { background: #ecf5ff; color: #337ecc; }
.draft-list button:disabled { cursor: default; }
.draft-list-top { display: flex; justify-content: space-between; gap: 10px; font-size: 12px; }
.draft-list small { display: block; margin-top: 5px; font-size: 11px; color: #909399; }
.draft-detail, .draft-empty { min-width: 0; padding: 22px; border: 1px solid #e4e7ed; border-radius: 6px; background: #fff; }
.detail-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.detail-heading h3 { margin: 0; font-weight: 500; font-size: 17px; }
.expiry { color: #909399; font-size: 12px; margin: 7px 0 16px; }
.draft-product { padding: 13px 0; border-top: 1px solid #ebeef5; }
.draft-product strong { font-weight: 500; font-size: 14px; }
.draft-product strong > span { color: #909399; margin-left: 7px; font-weight: normal; }
.draft-product p { margin: 5px 0 0; color: #909399; font-size: 12px; overflow-wrap: anywhere; }
.draft-product p.error { color: #b88230; }
.draft-total { display: flex; align-items: baseline; justify-content: space-between; padding: 16px 0; border-top: 1px solid #ebeef5; }
.draft-total > strong { font-size: 23px; font-weight: 500; }
.current-total { color: #b88230; font-size: 12px; }
.shipping-form { border-top: 1px solid #ebeef5; margin-top: 10px; padding-top: 18px; }
.shipping-form h3 { margin: 0; font-weight: 500; font-size: 15px; }
.privacy-note { color: #909399; font-size: 12px; margin: 5px 0 16px; }
.shipping-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.shipping-form label { display: block; font-size: 13px; color: #606266; margin-bottom: 14px; }
.shipping-form label > .el-input { display: flex; margin-top: 6px; }
.confirm-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
.confirm-actions :deep(.el-button + .el-button) { margin-left: 0; }
.draft-meta { margin-top: 22px; padding-top: 12px; border-top: 1px solid #ebeef5; color: #909399; font-size: 11px; overflow-wrap: anywhere; }
.draft-meta summary { cursor: pointer; }
.draft-meta p { margin: 8px 0 0; }
.checkout-entry { border-top: 1px solid #ebeef5; margin-top: 18px; padding-top: 14px; }
.checkout-entry p { font-size: 12px; color: #909399; margin: 0 0 12px; }
.draft-footer { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; margin-top: 14px; color: #909399; font-size: 12px; }
.draft-footer > .el-button { font-size: 12px; }
@media(max-width: 760px) {
  .draft-page { padding: 16px 12px; }
  .draft-header { flex-wrap: wrap; gap: 12px; }
  .draft-layout { grid-template-columns: minmax(0, 1fr); gap: 12px; }
  .draft-list { display: flex; align-items: center; gap: 6px; overflow-x: auto; padding: 8px; }
  .draft-list h3 { display: none; }
  .draft-list button { width: 200px; flex-shrink: 0; margin: 0; }
  .draft-detail { padding: 16px; }
}
@media(max-width: 420px) { .shipping-grid { grid-template-columns: minmax(0, 1fr); gap: 0; } }
</style>
