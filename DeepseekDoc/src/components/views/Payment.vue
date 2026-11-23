<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ElMessageBox } from "element-plus";
import { ArrowLeft, Refresh, Lock, CircleCheck } from "@element-plus/icons-vue";
import { useUserStore } from "@/stores/userStore";
import { useWalletStore } from "@/stores/walletStore";
import { createPaymentClient, paymentsEnabled, paymentStatusLabel } from "@/services/paymentClient.mjs";
import { browserPaymentRecovery } from "@/services/paymentRecovery.mjs";
import { createPaymentFlow } from "@/services/paymentFlow.mjs";

const route = useRoute();
const user = useUserStore();
const wallet = useWalletStore();
const api = createPaymentClient({ baseURL: import.meta.env.VITE_API_BASE || "" });
const state = ref({ phase: "idle" });
const password = ref("");
const verificationOpen = ref(false);
const clock = ref(Math.floor(Date.now() / 1000));
const owner = () => ({ userId: user.userId, token: user.token });
const flow = createPaymentFlow({ api, getOwner: owner, recovery: browserPaymentRecovery(),
  onChange: value => { state.value = value; },
  onSessionExpired: original => {
    if (original.token === user.token && original.userId === user.userId
      && localStorage.getItem("token") === original.token) {
      localStorage.removeItem("token");
      localStorage.removeItem("healthToken");
      window.dispatchEvent(new Event("auth-expired"));
    }
  },
});
const order = computed(() => state.value.order);
const remaining = computed(() => Math.max(0, (order.value?.expiresAt || 0) - clock.value));
const authorizationRemaining = computed(() => Math.min(60, Math.max(0, (state.value.authorizationExpiresAt || 0) - clock.value)));
const lockRemaining = computed(() => Math.max(0, (state.value.verificationLockedUntil || 0) - clock.value));
const waiting = computed(() => ["uncertain", "paying", "loading", "closing"].includes(state.value.phase));
const canVerify = computed(() => paymentsEnabled && state.value.phase === "ready" && remaining.value > 0 && lockRemaining.value === 0);
const canPay = computed(() => paymentsEnabled && state.value.phase === "authorized" && authorizationRemaining.value > 0 && remaining.value > 0);
const countdown = computed(() => `${Math.floor(remaining.value / 60)}:${String(remaining.value % 60).padStart(2, "0")}`);
const closeReason = computed(() => ({ EXPIRED: "付款期限已过", USER_CANCELLED: "用户主动关闭", CATALOG_CHANGED: "商品价格或销售资格已变化" }[order.value?.closeReason] || "订单已关闭"));

function refresh() {
  password.value = "";
  verificationOpen.value = false;
  if (paymentsEnabled) void flow.load(String(route.params.orderId || ""));
}
function openVerification() {
  if (!canVerify.value) return;
  password.value = "";
  verificationOpen.value = true;
}
function cancelVerification() {
  password.value = "";
  verificationOpen.value = false;
  flow.cancelAuthorization();
}
function verificationVisibilityChanged(value) {
  // Dialog's closing transition also emits false after a successful programmatic close.
  if (!value && verificationOpen.value) cancelVerification();
}
async function verify() {
  if (!password.value || state.value.busy) return;
  const pending = flow.authorize(password.value);
  password.value = "";
  await pending;
  if (state.value.phase === "authorized") verificationOpen.value = false;
}
async function closeOrder() {
  const original = owner();
  const id = route.params.orderId;
  try { await ElMessageBox.confirm("关闭后不能继续付款，需重新准备草稿。", "关闭待付款订单", { confirmButtonText: "关闭订单", cancelButtonText: "保留订单", type: "warning" }); }
  catch { return; }
  if (original.token === user.token && original.userId === user.userId && id === route.params.orderId) await flow.close();
}
watch(() => [route.params.orderId, user.token, user.userId], () => {
  password.value = "";
  verificationOpen.value = false;
  flow.dispose();
  if (user.token && paymentsEnabled) refresh();
}, { immediate: true, flush: "sync" });
watch(() => state.value.phase, async phase => {
  if (phase !== "paid") return;
  const original = owner();
  try {
    const data = await api.wallet(original);
    if (original.token === user.token && original.userId === user.userId) wallet.updateAfterOrder(data.balance, data.points);
  } catch {}
});
const timer = setInterval(() => { clock.value = Math.floor(Date.now() / 1000); flow.tick(); }, 1000);
function leavePage() { password.value = ""; verificationOpen.value = false; flow.dispose(); }
function restoredPage(event) { if (event.persisted) refresh(); }
window.addEventListener("pagehide", leavePage);
window.addEventListener("pageshow", restoredPage);
onBeforeUnmount(() => {
  clearInterval(timer);
  window.removeEventListener("pagehide", leavePage);
  window.removeEventListener("pageshow", restoredPage);
  leavePage();
});
</script>

<template>
  <main class="payment-page">
    <header class="payment-header">
      <div><h2>独立付款</h2><p>核对订单 · 验证密码 · 明确付款</p></div>
      <div class="header-actions">
        <RouterLink to="/payments"><el-button :icon="ArrowLeft" plain>我的订单</el-button></RouterLink>
        <el-button :icon="Refresh" :disabled="state.busy || !paymentsEnabled" @click="refresh">{{ state.phase === 'uncertain' ? '查询付款结果' : '刷新' }}</el-button>
      </div>
    </header>
    <el-alert v-if="!paymentsEnabled" title="本环境尚未启用独立付款，请使用隔离演示环境。" type="info" :closable="false" show-icon />
    <div v-else>
      <el-alert v-if="state.message" :title="state.message" :type="state.phase === 'uncertain' ? 'warning' : state.phase === 'authorized' ? 'success' : 'info'" :closable="false" show-icon role="status" />
      <el-alert v-if="state.cleanupWarning" :title="state.cleanupWarning" type="warning" :closable="false" show-icon />
      <p v-if="state.phase === 'loading'" class="loading-note" role="status">正在读取本人订单…</p>
      <div v-if="order" class="payment-layout">
        <section class="order-panel">
          <div class="order-heading"><h3>{{ paymentStatusLabel(order.paymentStatus) }}</h3><el-tag effect="plain" size="small">演示钱包 · CNY</el-tag></div>
          <p class="order-id">订单 {{ order.orderId }}</p>
          <article v-for="item in order.items" :key="item.medicineId" class="payment-item">
            <div><strong>{{ item.name || '历史商品' }}</strong><p>单价 ¥{{ item.price }} · {{ item.quantity }} 件</p></div>
            <span class="item-quantity">× {{ item.quantity }}</span>
          </article>
          <details class="shipping-details"><summary>查看已确认的收货资料</summary>
            <p>{{ order.recipientName }} · {{ order.recipientPhone }}</p><p>{{ order.recipientAddress }}</p>
            <small>仅用于订单履约，不发送给AI。</small>
          </details>
          <p v-if="state.phase === 'closed'" class="order-note">{{ closeReason }}。<RouterLink to="/drafts">返回草稿</RouterLink></p>
          <p v-if="state.phase === 'legacy'" class="order-note">历史业务状态不能作为新流程付款凭据。</p>
        </section>
        <aside class="payment-summary" aria-label="付款操作">
          <p class="summary-label">{{ state.phase === 'paid' ? '已付金额' : '订单金额' }}</p>
          <strong class="amount">¥{{ order.totalPrice }}</strong>
          <template v-if="state.phase === 'paid'">
            <p class="paid-note"><el-icon><CircleCheck /></el-icon>付款成功</p>
            <p v-if="state.receipt" class="receipt">支付单号 {{ state.receipt.paymentId }}<br>付款时间 {{ new Date(state.receipt.paidAt * 1000).toLocaleString() }}</p>
            <RouterLink to="/payments"><el-button class="wide" type="primary" plain>查看我的订单</el-button></RouterLink>
          </template>
          <template v-else-if="order.paymentStatus === 'PENDING_PAYMENT'">
            <p class="deadline">{{ remaining > 0 ? `剩余付款时间 ${countdown}` : '付款期限已到，请刷新核对' }}</p>
            <p class="summary-note">订单不预占库存；付款时将再次核对价格、资格、库存和余额。</p>
            <p v-if="lockRemaining" class="order-note">验证锁定中，还需等待 {{ lockRemaining }} 秒。</p>
            <p v-if="state.phase === 'authorized'" class="authorization-note">验证有效期剩余 {{ authorizationRemaining }} 秒</p>
            <el-button v-if="state.phase === 'authorized'" type="primary" class="wide" :disabled="!canPay" @click="flow.pay">确认付款 ¥{{ order.totalPrice }}</el-button>
            <el-button v-else-if="state.phase === 'uncertain'" type="primary" plain class="wide" @click="refresh">查询付款结果</el-button>
            <el-button v-else type="primary" class="wide" :icon="Lock" :loading="state.phase === 'paying'" :disabled="!canVerify" @click="openVerification">{{ state.phase === 'paying' ? '正在提交付款' : '验证支付密码' }}</el-button>
            <el-button v-if="state.phase === 'authorized'" class="wide" @click="cancelVerification">撤回本次支付授权</el-button>
            <div class="wallet-links"><RouterLink :to="user.isHealthWalletActive ? '/charge' : '/activate'">{{ user.isHealthWalletActive ? '演示钱包充值' : '激活演示钱包' }}</RouterLink>
              <el-button link :disabled="waiting || state.busy || !['ready', 'authorized'].includes(state.phase)" @click="closeOrder">关闭订单</el-button></div>
            <p class="safety-note">验证本身不扣款。只有点击“确认付款”才提交付款，AI没有付款权限。</p>
          </template>
          <RouterLink v-else to="/drafts"><el-button class="wide" plain>返回草稿</el-button></RouterLink>
        </aside>
      </div>
      <el-empty v-if="!order && !state.busy" description="暂无可显示的本人订单，请刷新或返回订单列表" :image-size="75" />
    </div>
    <el-dialog :model-value="verificationOpen" title="验证本次付款" width="min(420px, calc(100vw - 24px))" append-to-body
      :close-on-click-modal="false" :close-on-press-escape="true" destroy-on-close @update:model-value="verificationVisibilityChanged">
      <form class="verification-form" @submit.prevent="verify">
        <p>订单金额 <strong>¥{{ order?.totalPrice }}</strong> · 演示钱包</p>
        <p class="dialog-note">密码仅用于独立验证，不发送给AI；验证通过后还需明确点击付款。</p>
        <label>支付密码<el-input v-model="password" type="password" autocomplete="off" maxlength="72" aria-label="支付密码" placeholder="请输入支付密码" :disabled="state.phase === 'authorizing'" /></label>
        <p v-if="state.message && state.phase === 'ready'" class="dialog-error" role="alert">{{ state.message }}</p>
        <div class="verification-actions"><el-button @click="cancelVerification">撤回验证</el-button><el-button type="primary" native-type="submit" :loading="state.phase === 'authorizing'" :disabled="!password || lockRemaining > 0">验证（不扣款）</el-button></div>
      </form>
    </el-dialog>
  </main>
</template>

<style scoped>
.payment-page { max-width: 1040px; margin: 0 auto; padding: 24px; line-height: 1.7; color: #303133; }
.payment-header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; }
h2, h3, p { margin: 0; }
h2 { font-size: 20px; font-weight: 500; }
h3 { font-size: 17px; font-weight: 500; }
.payment-header p, .order-id, .summary-note, .deadline, .order-note, .safety-note, .receipt { font-size: 12px; color: #909399; }
.header-actions { display: flex; gap: 8px; }
.payment-layout { display: grid; grid-template-columns: minmax(0, 1fr) 310px; gap: 18px; align-items: start; margin-top: 16px; }
.order-panel, .payment-summary { min-width: 0; background: #fff; border: 1px solid #e4e7ed; border-radius: 6px; padding: 22px; }
.order-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.order-id { margin: 7px 0 18px; overflow-wrap: anywhere; }
.payment-item { display: flex; justify-content: space-between; align-items: start; gap: 14px; border-top: 1px solid #ebeef5; padding: 14px 0; }
.payment-item strong { font-size: 14px; font-weight: 500; overflow-wrap: anywhere; }
.payment-item p, .item-quantity { color: #909399; font-size: 12px; }
.item-quantity { flex-shrink: 0; }
.shipping-details { padding-top: 14px; border-top: 1px solid #ebeef5; color: #606266; font-size: 12px; overflow-wrap: anywhere; }
.shipping-details summary { cursor: pointer; }
.shipping-details p { margin-top: 8px; }
.shipping-details small { display: block; margin-top: 6px; color: #909399; }
.summary-label { color: #606266; font-size: 13px; }
.amount { display: block; font-size: 30px; font-weight: 500; margin: 4px 0 10px; overflow-wrap: anywhere; }
.summary-note { margin: 12px 0 18px; }
.wide { width: 100%; margin: 0 0 10px; }
.wide + .wide { margin-left: 0; }
.wallet-links { display: flex; justify-content: space-between; gap: 12px; align-items: center; font-size: 12px; margin-top: 4px; }
.wallet-links a, .order-note a { color: #409eff; text-decoration: none; }
.wallet-links .el-button { font-size: 12px; }
.safety-note { margin-top: 14px; padding-top: 12px; border-top: 1px solid #ebeef5; }
.authorization-note { font-size: 12px; color: #67a23a; margin-bottom: 10px; }
.paid-note { color: #529b2e; display: flex; align-items: center; gap: 6px; margin-bottom: 12px; }
.receipt { overflow-wrap: anywhere; margin: 0 0 20px; }
.order-note { margin-top: 14px; }
.loading-note { color: #909399; padding: 30px 0; }
.payment-page :deep(.el-alert + .el-alert) { margin-top: 10px; }
.verification-form { line-height: 1.7; }
.dialog-note { font-size: 12px; color: #909399; margin: 8px 0 18px; }
.verification-form label { display: block; font-size: 13px; }
.verification-form .el-input { margin-top: 7px; }
.verification-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 22px; }
.verification-actions .el-button + .el-button { margin-left: 0; }
.dialog-error { font-size: 12px; color: #b88230; margin-top: 10px; }
@media(max-width: 760px) {
  .payment-page { padding: 16px 12px; }
  .payment-layout { grid-template-columns: minmax(0, 1fr); gap: 12px; }
  .order-panel, .payment-summary { padding: 16px; }
}
</style>
