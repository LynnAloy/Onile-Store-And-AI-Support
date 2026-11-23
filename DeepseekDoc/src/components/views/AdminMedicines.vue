<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { useUserStore } from "@/stores/userStore";
import { createCommerceClient } from "@/services/commerceClient.mjs";

const user = useUserStore();
const client = createCommerceClient();
const rows = ref([]);
const error = ref("");
const busy = ref(false);
const editing = ref(null);
const mode = ref("");
const form = ref({});
const audit = ref([]);
const auditOpen = ref(false);
const owner = () => ({ token: user.token, userId: user.userId });
async function load() {
  const captured = owner();
  busy.value = true;
  try { const data = await client.medicines(captured); if (captured.token === user.token) rows.value = data; }
  catch (err) { error.value = err.message; }
  finally { busy.value = false; }
}
function edit(row, kind) {
  editing.value = row;
  mode.value = kind;
  form.value = kind === "stock" ? { stock: row.stock, reason: "" }
    : { classification: row.sale_classification, reviewStatus: row.review_status, referenceSource: row.reference_source || "" };
}
async function save() {
  const row = editing.value;
  const captured = owner();
  busy.value = true;
  try {
    await client[mode.value === "stock" ? "stock" : "review"](row.id,
      { ...form.value, expectedVersion: row.qualification_version, ...(mode.value === 'stock' ? { expectedStock: row.stock } : {}) }, captured);
    editing.value = null;
    ElMessage.success("已保存并记录审计");
    await load();
  } catch (err) { ElMessage.error(err.message); }
  finally { busy.value = false; }
}
async function showAudit(row) {
  try { audit.value = await client.audit(row.id, owner()); auditOpen.value = true; }
  catch (err) { ElMessage.error(err.message); }
}
onMounted(load);
</script>

<template>
  <section class="admin-page">
    <header><div><h2>药品管理</h2><p>库存、销售分类与审核记录</p></div><el-button :loading="busy" @click="load">刷新</el-button></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-table :data="rows" v-loading="busy" stripe>
      <el-table-column prop="id" label="ID" width="65" />
      <el-table-column prop="name" label="商品" min-width="140" />
      <el-table-column prop="price" label="单价" width="85" />
      <el-table-column prop="stock" label="库存" width="75" />
      <el-table-column label="销售分类" width="110"><template #default="{ row }">{{ { OTC: '非处方药', RX: '处方药', UNKNOWN: '待分类' }[row.sale_classification] }}</template></el-table-column>
      <el-table-column label="审核" width="90"><template #default="{ row }">{{ row.review_status === 'APPROVED' ? '已通过' : '待审核' }}</template></el-table-column>
      <el-table-column prop="qualification_version" label="版本" width="65" />
      <el-table-column label="操作" min-width="220"><template #default="{ row }">
        <el-button link type="primary" @click="edit(row, 'stock')">调整库存</el-button>
        <el-button link type="primary" @click="edit(row, 'review')">分类审核</el-button>
        <el-button link @click="showAudit(row)">记录</el-button>
        <RouterLink :to="'/admin/medicines/' + row.id + '/evidence'" class="evidence-link">审核证据</RouterLink>
      </template></el-table-column>
    </el-table>
    <p class="note">分类和审核分别保存。只有 OTC 且审核通过、依据完整的商品可由 AI 下单；处方药不进入自动下单流程。</p>
    <el-dialog :model-value="!!editing" :title="mode === 'stock' ? '调整库存' : '销售分类审核'" width="min(520px, 94vw)" @close="editing = null">
      <p>{{ editing?.name }} · 当前版本 {{ editing?.qualification_version }}</p>
      <el-form label-position="top" :disabled="busy">
        <template v-if="mode === 'stock'">
          <el-form-item label="调整后库存"><el-input-number v-model="form.stock" :min="0" :max="2147483647" :precision="0" /></el-form-item>
          <el-form-item label="调整原因"><el-input v-model="form.reason" maxlength="200" /></el-form-item>
        </template>
        <template v-else>
          <el-form-item label="销售分类"><el-radio-group v-model="form.classification"><el-radio value="OTC">非处方药</el-radio><el-radio value="RX">处方药</el-radio><el-radio value="UNKNOWN">待分类</el-radio></el-radio-group></el-form-item>
          <el-form-item label="审核结果"><el-radio-group v-model="form.reviewStatus"><el-radio value="PENDING">待审核</el-radio><el-radio value="APPROVED">审核通过</el-radio></el-radio-group></el-form-item>
          <el-form-item label="审核依据（通过时必填）"><el-input v-model="form.referenceSource" maxlength="255" placeholder="https://… 或 local://…" /></el-form-item>
          <p class="note">请核实商品说明书与销售资格后再通过审核。操作者由服务器记录。</p>
        </template>
      </el-form>
      <template #footer><el-button @click="editing = null">取消</el-button><el-button type="primary" :loading="busy" @click="save">保存</el-button></template>
    </el-dialog>
    <el-drawer v-model="auditOpen" title="商品变更记录" size="min(600px, 95vw)">
      <p v-if="!audit.length">暂无管理员变更记录</p>
      <article v-for="entry in audit" :key="entry.id" class="audit-entry">
        <p>{{ new Date(entry.created_at * 1000).toLocaleString() }} · 管理员 {{ entry.admin_id }}</p>
        <pre>{{ JSON.stringify(JSON.parse(entry.after_json), null, 2) }}</pre>
      </article>
    </el-drawer>
  </section>
</template>

<style scoped>
.admin-page { max-width: 1200px; padding: 24px; margin: auto; }
header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 22px; }
h2 { margin: 0 0 8px; font-size: 21px; }
header p, .note { color: #909399; font-size: 13px; line-height: 1.8; }
.audit-entry { border-bottom: 1px solid #ebeef5; padding: 12px 0; font-size: 13px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; color: #606266; }
</style>
