<script setup>
import { RouterView, useRouter, useRoute } from "vue-router";
import { ChatDotRound, User, ArrowDown } from "@element-plus/icons-vue";
import MenuUI from "@/components/views/Menu.vue";
import { useUserStore } from "@/stores/userStore";

const router = useRouter();
const route = useRoute();
const demoMode = import.meta.env.VITE_DEMO_MODE === "true";
const userStore = useUserStore();
const accountAction = (command) => command === "logout" ? userStore.logout() : router.push("/info");
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="brand"><el-icon :size="23"><ChatDotRound /></el-icon><span>Deepseek-智能体</span><el-tag v-if="demoMode" type="warning" size="small">虚构演示</el-tag></div>
      <el-dropdown v-if="userStore.isLoggedIn" trigger="click" @command="accountAction">
        <el-button :icon="User" plain>个人账号<el-icon class="account-arrow"><ArrowDown /></el-icon></el-button>
        <template #dropdown><el-dropdown-menu>
          <el-dropdown-item command="profile">个人中心</el-dropdown-item>
          <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
        </el-dropdown-menu></template>
      </el-dropdown>
      <el-button v-else :icon="User" type="primary" plain @click="router.push('/login')">登录</el-button>
    </header>
    <div class="shell-body">
      <aside class="app-sidebar"><MenuUI /></aside>
      <main class="app-main" :class="{ 'is-chat': route.path === '/main' }">
        <RouterView :show-name="'智能问诊平台'" />
      </main>
    </div>
  </div>
</template>

<style>
html, body, #app { width: 100%; height: 100%; min-width: 320px; margin: 0; }
body { color: #303133; font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif; font-size: 14px; }
*, *::before, *::after { box-sizing: border-box; }
button, input, textarea, select { font: inherit; }
a { color: #409eff; text-decoration: none; }
a:hover { color: #337ecc; }
button:focus-visible, a:focus-visible, summary:focus-visible { outline: 2px solid #409eff; outline-offset: 3px; }
</style>

<style scoped>
.app-shell { height: 100vh; height: 100dvh; display: grid; grid-template-rows: 56px minmax(0, 1fr); background: #fff; }
.app-header { display: flex; align-items: center; justify-content: space-between; padding: 0 24px; border-bottom: 1px solid #e4e7ed; }
.brand { display: flex; align-items: center; gap: 10px; font-size: 17px; font-weight: 600; letter-spacing: .2px; }
.brand .el-icon { color: #409eff; }
.account-arrow { margin-left: 8px; }
.app-main :deep(.el-card) { box-shadow: none; }
.shell-body { display: grid; grid-template-columns: 176px minmax(0, 1fr); min-height: 0; }
.app-sidebar { min-height: 0; overflow-y: auto; border-right: 1px solid #e4e7ed; }
.app-main { min-width: 0; min-height: 0; overflow: auto; background: #f5f7fa; }
.app-main.is-chat { padding: 16px; overflow: hidden; }
@media (max-width: 760px) {
  .app-header { padding: 0 16px; }
  .brand { font-size: 14px; gap: 6px; }
  .brand > span { white-space: nowrap; }
  .shell-body { grid-template-columns: minmax(0, 1fr); grid-template-rows: 48px minmax(0, 1fr); }
  .app-sidebar { border-right: 0; border-bottom: 1px solid #e4e7ed; overflow: hidden; }
  .app-main.is-chat { padding: 8px; }
}
@media (max-width: 420px) {
  .app-shell { grid-template-rows: 50px minmax(0, 1fr); }
  .brand { font-size: 15px; }
}
</style>
