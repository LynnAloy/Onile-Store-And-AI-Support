import { createApp } from "vue";
import { createPinia } from "pinia";
import ElementPlus from "element-plus";
import * as ElementPlusIconsVue from "@element-plus/icons-vue";
import "element-plus/dist/index.css";
import AppHome from "@/AppHome.vue";  // 使用 @/ 表示 src 目录
import router from "@/router/config.js";

// 首先创建应用实例
const pinia = createPinia();
const app = createApp(AppHome);

// 然后注册所有 Element Plus 图标组件
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component);
}

// 使用路由和 ElementPlus 插件
app.use(pinia);
app.use(router);
app.use(ElementPlus);

// 最后挂载应用
app.mount('#app');