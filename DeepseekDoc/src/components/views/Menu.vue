<script setup>
import { useRoute } from "vue-router";
import { ref, watch } from "vue";
import { useUserStore } from "@/stores/userStore";
import { commerceEnabled, createCommerceClient } from "@/services/commerceClient.mjs";
import { ChatDotRound, User, ShoppingBag, DocumentChecked, Wallet } from "@element-plus/icons-vue";
import { paymentsEnabled } from "@/services/paymentClient.mjs";

const route = useRoute();
const user = useUserStore();
const isAdmin = ref(false);
watch(() => user.token, async token => {
  isAdmin.value = false;
  if (!commerceEnabled || !token) return;
  try {
    const result = await createCommerceClient().permissions({ token });
    if (token === user.token) isAdmin.value = result.admin === true;
  } catch {}
}, { immediate: true });
</script>

<template>
  <el-menu :default-active="route.path" router class="app-menu">
    <el-menu-item v-if="isAdmin" index="/admin/ai-config"><el-icon><ChatDotRound /></el-icon><span>模型配置</span></el-menu-item>
    <el-menu-item v-if="isAdmin" index="/admin/medicines"><el-icon><ShoppingBag /></el-icon><span>药品管理</span></el-menu-item>
    <el-menu-item index="/main"><el-icon><ChatDotRound /></el-icon><span>首页对话</span></el-menu-item>
    <el-menu-item index="/info"><el-icon><User /></el-icon><span>个人中心</span></el-menu-item>
    <el-menu-item index="/form"><el-icon><ShoppingBag /></el-icon><span>在线购药</span></el-menu-item>
    <el-menu-item index="/drafts"><el-icon><DocumentChecked /></el-icon><span>我的草稿</span></el-menu-item>
    <el-menu-item v-if="paymentsEnabled" index="/payments"><el-icon><Wallet /></el-icon><span>付款订单</span></el-menu-item>
  </el-menu>
</template>

<style scoped>
.app-menu { border: 0; padding: 16px 8px; }
.app-menu .el-menu-item { height: 46px; margin: 3px 0; border-radius: 5px; color: #606266; }
.app-menu .el-menu-item.is-active { color: #409eff; background: #ecf5ff; }
.app-menu .el-menu-item:hover { background: #f5f7fa; }
.app-menu .el-menu-item .el-icon { margin-right: 10px; }
@media (max-width: 760px) {
  .app-menu { display: flex; width: 100%; padding: 0 6px; }
  .app-menu .el-menu-item { flex: 1; justify-content: center; min-width: 0; height: 43px; padding: 0 7px; font-size: 12px; }
  .app-menu .el-menu-item .el-icon { width: 16px; margin-right: 3px; font-size: 16px; }
  .app-menu .el-menu-item { padding: 0 3px; font-size: 11px; }
}
</style>
