import { createRouter, createWebHistory } from "vue-router";
import Home from "@/components/views/Home.vue"; // 确保路径正确
import Form from "@/components/views/Form.vue"; // 使用 Form.vue 文件
import { useUserStore } from "@/stores/userStore";

//路由规则 url=>组件
const routes = [
  { path: "/admin/medicines/:id/evidence", component: () => import("@/components/views/AdminMedicineEvidence.vue") },
  { path: "/admin/ai-config", component: () => import("@/components/views/AdminAIConfig.vue") },
  { path: "/admin/medicines", name: "admin-medicines", component: () => import("@/components/views/AdminMedicines.vue") },
  { path: "/payment/:orderId", name: "payment", component: () => import("@/components/views/Payment.vue") },
  { path: "/payments", name: "payments", component: () => import("@/components/views/PaymentOrders.vue") },
  { path: "/drafts", name: "drafts", component: () => import("@/components/views/Drafts.vue") },
  {
    path: "/",
    redirect: (to) => "/main", // 重定向到 /main 路径
    name: "root"
  },
  {
    path: "/main",
    name: "main", // 给路由起个名字，方便后面的跳转，比如：this.$router.push({name:'home'})，就会跳转到首页，而不是根路径/
    component: () => import("@/components/views/Home.vue"),
    props: { showName: "Deepseek 家庭医生" }, // 添加这行
  },
  {
    path: "/info",
    name: "info",
    component: () => import("@/components/views/Info.vue"),
  },
  {
    path: "/form",
    name: "form",
    component: () => import("@/components/views/Form.vue"),
  },
  {
    path: "/login",
    name: "login",
    component: () => import("@/components/views/Login.vue"),
  },
  {
    path:"/logout",
    name:"logout",
    component:()=>import("@/components/views/Logout.vue")
  },
  {
    path:"/activate",
    name:"activate",
    component:()=>import("@/components/views/Activate.vue")
  },
  {
    path:"/charge",
    name:"charge",
    component:()=>import("@/components/views/Charge.vue")
  },
  {
    path:"/shoppingsuccess",
    name:"shoppingsuccess",
    component:()=>import("@/components/views/ShoppingSuccess.vue")
  },
  {
    path:"/shoppingfail",
    name:"shoppingfail",
    component:()=>import("@/components/views/ShoppingFail.vue")
  },
  {
    path:"/register",
    name:"register",
    component:()=>import("@/components/views/Register.vue")
  }
];

//创建路由器对象(实例)
const router = createRouter({
  history: createWebHistory(),
  routes: routes,
});

// 修正后的路由守卫
router.beforeEach((to, from, next) => {
  const userStore = useUserStore();
  // 标准化路径：移除尾部斜杠并转为小写
  const normalizePath = (path) => 
    path.replace(/\/$/, "").toLowerCase();
  
  const currentPath = normalizePath(to.path);
  const publicPaths = [
    '/login', 
    '/main',
    '/register',
  ].map(p => normalizePath(p));

  if(currentPath === normalizePath('/activate') && userStore.healthToken){
    next('/charge');
    return;
  }

  // 使用标准化路径检查
  if (publicPaths.includes(currentPath)) {
    next();
    return;
  }

  // 检查token
  if (!userStore.token) {
    next(`/login?redirect=${encodeURIComponent(to.fullPath)}`);
  } else {
    next();
  }
});

export default router;
