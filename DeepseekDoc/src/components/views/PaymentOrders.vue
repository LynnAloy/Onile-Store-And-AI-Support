<script setup>
import { onBeforeUnmount, ref, watch } from "vue";
import { Refresh, ArrowLeft } from "@element-plus/icons-vue";
import { useUserStore } from "@/stores/userStore";
import { createPaymentClient, paymentsEnabled, paymentStatusLabel } from "@/services/paymentClient.mjs";

const user = useUserStore();
const api = createPaymentClient({ baseURL: import.meta.env.VITE_API_BASE || "" });
const orders = ref([]);
const loading = ref(false);
const errorText = ref("");
let epoch = 0;
async function refresh() {
  const ticket = ++epoch;
  const owner = { userId: user.userId, token: user.token };
  orders.value = [];
  errorText.value = "";
  if (!owner.token || !paymentsEnabled) return;
  loading.value = true;
  const current = () => ticket === epoch && owner.token === user.token && owner.userId === user.userId;
  try {
    const data = await api.list(owner);
    if (current()) orders.value = data;
  } catch (error) {
    if (current()) errorText.value = error.message || "订单查询未完成";
  } finally { if (current()) loading.value = false; }
}
watch(() => [user.token, user.userId], refresh, { immediate: true, flush: "sync" });
onBeforeUnmount(() => { epoch++; orders.value = []; });
</script>

<template>
  <main class="payment-orders">
    <header><div><h2>付款订单</h2><p>最近50笔本人订单 · 按服务端结果显示</p></div><div class="actions">
      <RouterLink to="/drafts"><el-button :icon="ArrowLeft" plain>我的草稿</el-button></RouterLink>
      <el-button :icon="Refresh" :disabled="loading || !paymentsEnabled" @click="refresh">刷新</el-button>
    </div></header>
    <el-alert v-if="!paymentsEnabled" title="本环境未启用独立付款。原业务订单可在个人中心查看。" type="info" :closable="false" show-icon />
    <el-alert v-if="errorText" :title="errorText" type="error" :closable="false" show-icon />
    <section v-loading="loading" class="orders-list">
      <article v-for="order in orders" :key="order.orderId" class="order-row">
        <div class="row-main"><strong>{{ paymentStatusLabel(order.paymentStatus) }}</strong><p>{{ order.orderId }}</p>
          <p>{{ order.items.map(item => `${item.name || '历史商品'} × ${item.quantity}`).join('、') }}</p>
        </div>
        <div class="row-action"><strong>¥{{ order.totalPrice }}</strong><RouterLink :to="`/payment/${encodeURIComponent(order.orderId)}`"><el-button size="small" :type="order.paymentStatus === 'PENDING_PAYMENT' ? 'primary' : 'default'" plain>{{ order.paymentStatus === 'PENDING_PAYMENT' ? '核对并付款' : '查看订单' }}</el-button></RouterLink></div>
      </article>
      <el-empty v-if="paymentsEnabled && !orders.length && !loading" description="暂无订单，先从已确认的草稿进入付款" :image-size="75" />
    </section>
  </main>
</template>

<style scoped>
.payment-orders { max-width: 1040px; margin: 0 auto; padding: 24px; line-height: 1.7; }
header { display: flex; justify-content: space-between; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 18px; }
h2 { font-size: 20px; font-weight: 500; margin: 0; }
header p { font-size: 12px; color: #909399; margin: 0; }
.actions { display: flex; gap: 8px; }
.orders-list { margin-top: 16px; min-height: 100px; }
.order-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px; margin-bottom: 10px; border: 1px solid #e4e7ed; border-radius: 6px; background: #fff; }
.row-main { min-width: 0; }
.row-main > strong { font-size: 14px; font-weight: 500; }
.row-main p { color: #909399; font-size: 12px; margin: 5px 0 0; overflow-wrap: anywhere; }
.row-action { flex-shrink: 0; text-align: right; }
.row-action > strong { display: block; font-weight: 500; font-size: 18px; margin-bottom: 8px; }
@media(max-width: 760px) { .payment-orders { padding: 16px 12px; } .order-row { align-items: start; padding: 14px; } }
</style>
