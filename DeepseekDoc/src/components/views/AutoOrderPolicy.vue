<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { useUserStore } from "@/stores/userStore";
import { createCommerceClient } from "@/services/commerceClient.mjs";

const user = useUserStore();
const client = createCommerceClient();
const policy = ref(null);
const form = ref({ enabled: false, perOrderLimit: 50, dailyLimit: 200 });
const password = ref("");
const busy = ref(false);
const error = ref("");
const owner = () => ({ token: user.token, userId: user.userId });
const current = captured => captured.token === user.token && captured.userId === user.userId;
function display(value) {
  policy.value = value;
  form.value = { enabled: value.enabled, perOrderLimit: Number(value.perOrderLimit), dailyLimit: Number(value.dailyLimit) };
}
async function load() {
  const captured = owner();
  try { const value = await client.policy(captured); if (current(captured)) display(value); }
  catch (err) { if (current(captured)) error.value = err.message; }
}
async function save(disable = false) {
  if (!policy.value || busy.value) return;
  const captured = owner();
  busy.value = true;
  error.value = "";
  const body = disable
    ? { enabled: false, perOrderLimit: Number(policy.value.perOrderLimit), dailyLimit: Number(policy.value.dailyLimit) }
    : { ...form.value };
  body.expectedVersion = policy.value.version;
  body.password = password.value || undefined;
  password.value = "";
  try {
    const value = await client.updatePolicy(body, captured);
    if (current(captured)) { display(value); window.dispatchEvent(new Event("auto-order-policy-changed")); ElMessage.success("智能下单设置已保存"); }
  } catch (err) {
    if (current(captured)) { error.value = err.message; await load(); }
  } finally { body.password = undefined; busy.value = false; }
}
onMounted(load);
</script>

<template>
  <section class="auto-policy" aria-label="AI 智能下单授权">
    <h3>AI 智能下单</h3>
    <p>自动下单还需有效药品审核证据，以及已授权、完整的健康资料风险复核。仅对18至64岁，明确自述无病史、无已知过敏、无当前用药且其他健康信息填写“无其他健康风险”的情况开放；信息不足或存在风险时转人工核对。这不是用药适用性认证。</p>
    <p>开启后，明确的商品名称和数量可由 AI 自动下单并扣除演示钱包余额。仅限审核通过的非处方商品。</p>
    <p>使用个人资料中的收货人、手机和地址填单；收货资料不会发送给模型。关闭后需核对草稿并手动付款。</p>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" />
    <el-form v-if="policy" label-position="top" :disabled="busy" @submit.prevent="save()">
      <el-form-item><el-switch v-model="form.enabled" aria-label="允许 AI 智能下单" active-text="允许 AI 智能下单" /></el-form-item>
      <div class="limits">
        <el-form-item label="单笔最高（元）"><el-input-number v-model="form.perOrderLimit" :min="0.01" :max="99999999.99" :precision="2" /></el-form-item>
        <el-form-item label="每日累计最高（元）"><el-input-number v-model="form.dailyLimit" :min="0.01" :max="99999999.99" :precision="2" /></el-form-item>
      </div>
      <p>今日已用 ¥{{ Number(policy.dailySpent).toFixed(2) }} · 剩余 ¥{{ Number(policy.dailyRemaining).toFixed(2) }}<br>PST（固定 UTC−08:00）{{ policy.budgetDay }}，不随夏令时切换。</p>
      <el-form-item label="支付密码（开启、重新开启或提高额度时必填）">
        <el-input v-model="password" type="password" autocomplete="off" maxlength="72" placeholder="请输入支付密码" @keyup.enter="save()" />
      </el-form-item>
      <el-button type="primary" :loading="busy" @click="save()">保存授权设置</el-button>
      <el-button v-if="policy.enabled" type="danger" plain @click="save(true)">立即关闭</el-button>
      <p>授权仅对本次登录有效。重新登录需再次验证开启；关闭或重新登录均不会清零当天已用额度。</p>
    </el-form>
  </section>
</template>

<style scoped>
.auto-policy { padding: 20px 0; border-top: 1px solid #ebeef5; }
h3 { color: #409eff; margin: 0 0 14px; }
p { color: #606266; font-size: 13px; line-height: 1.8; }
.limits { display: flex; flex-wrap: wrap; gap: 24px; }
.el-form { margin-top: 18px; }
</style>
