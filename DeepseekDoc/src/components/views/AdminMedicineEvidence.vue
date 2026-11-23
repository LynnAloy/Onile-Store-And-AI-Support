<script setup>
import { onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { useUserStore } from '@/stores/userStore';
import { createCommerceClient } from '@/services/commerceClient.mjs';
const route = useRoute();
const user = useUserStore();
const client = createCommerceClient();
const form = ref(null);
const categories = ref('');
const ingredients = ref('');
const message = ref('');
const busy = ref(false);
const owner = () => ({ token: user.token });
async function load() {
  const captured = owner();
  try {
    const value = await client.evidence(route.params.id, captured);
    if (captured.token !== user.token) return;
    form.value = { ...value, source: value.source || '', indications: value.indications || '', maxUnitsPerOrder: value.maxUnitsPerOrder || 1 };
    categories.value = (value.categories || []).join('，');
    ingredients.value = (value.ingredients || []).join('，');
  } catch (error) { message.value = error.message; }
}
const split = text => text.split(/[,，\n]/).map(value => value.trim()).filter(Boolean);
async function save() {
  const captured = owner();
  busy.value = true;
  try {
    const value = await client.saveEvidence(route.params.id, {
      expectedVersion: form.value.version, qualificationVersion: form.value.qualificationVersion,
      categories: split(categories.value), ingredients: split(ingredients.value), source: form.value.source,
      indications: form.value.indications, maxUnitsPerOrder: form.value.maxUnitsPerOrder,
    }, captured);
    if (captured.token === user.token) { form.value = value; message.value = '已审核保存，类别检索与自动购买使用此版本。'; }
  } catch (error) { message.value = error.message; }
  finally { busy.value = false; }
}
onMounted(load);
</script>
<template>
  <section class="evidence-page">
    <h2>药品审核证据 · 商品 {{ route.params.id }}</h2>
    <p>依据商品说明书或审核材料填写。此处保存会作为管理员审核记录；不得将模型推测填为审核事实。</p>
    <RouterLink to="/admin/medicines">返回药品管理</RouterLink>
    <el-alert v-if="message" :title="message" :closable="false" />
    <el-alert v-if="form?.status === 'STALE'" title="商品版本已变化，旧证据已停用，请重新核实后保存。" type="warning" :closable="false" />
    <el-form v-if="form" label-position="top" :disabled="busy">
      <el-form-item label="审核类别（逗号分隔）"><el-input v-model="categories" maxlength="1000" /></el-form-item>
      <el-form-item label="成分（逗号分隔）"><el-input v-model="ingredients" maxlength="2000" /></el-form-item>
      <el-form-item label="适用范围审核原文"><el-input v-model="form.indications" type="textarea" :rows="4" maxlength="2000" /></el-form-item>
      <el-form-item label="说明书或审核材料来源"><el-input v-model="form.source" maxlength="500" placeholder="https://… 或 local://…" /></el-form-item>
      <el-form-item label="单次自动购买数量上限（商品件数，不是服药剂量）"><el-input-number v-model="form.maxUnitsPerOrder" :min="1" :max="99" :precision="0" /></el-form-item>
      <p>审核人由服务器记录；该证据仅对当前商品审核版本有效。商品仍需满足 OTC 销售资格；健康风险未知时不会自动扣款。</p>
      <el-button type="primary" :loading="busy" @click="save">确认审核并保存证据</el-button>
    </el-form>
  </section>
</template>
<style scoped>
.evidence-page { max-width: 800px; margin: auto; padding: 24px; }
h2 { font-size: 21px; }
p { color: #909399; font-size: 13px; line-height: 1.8; }
.el-form { margin-top: 20px; }
</style>
