import axios from "axios";
import { issueOwnerBoundOrderGrant } from "@/services/orderAuthorization.mjs";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || "",
  timeout: 15000,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token && !config.headers.Authorization) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const code = error.response?.data?.code;
    const currentToken = localStorage.getItem("token");
    const sentAuthorization = error.config?.headers?.Authorization;
    if (error.response?.status === 401 && code === "UNAUTHORIZED" && currentToken
      && sentAuthorization === `Bearer ${currentToken}`) {
      localStorage.removeItem("token");
      localStorage.removeItem("healthToken");
      window.dispatchEvent(new Event("auth-expired"));
    }
    const message = error.response?.data?.message || error.message || "请求失败";
    return Promise.reject(Object.assign(new Error(message), { code }));
  }
);

export default {
  register: (data) => api.post("/api/auth/register", data),
  login: (data) => api.post("/api/auth/login", data),
  logout: (userId, ownerToken) => api.post("/api/auth/logout", { userId }, {
    headers: { Authorization: `Bearer ${ownerToken}` },
  }),
  agentToken: () => api.post("/api/auth/agent-token"),
  orderAgentToken: (data, ownerToken) => issueOwnerBoundOrderGrant(data, ownerToken, {
    baseURL: import.meta.env.VITE_API_BASE || "",
  }),
  revokeOrderAgent: () => api.delete("/api/auth/order-agent-token"),
  revokeOrderGrant: async (requestKey, ownerToken) => {
    // Explicit original owner: a late response must not use another user's current interceptor token.
    const base = import.meta.env.VITE_API_BASE || "";
    const response = await fetch(`${base}/api/auth/order-agent-token?requestKey=${encodeURIComponent(requestKey)}`, {
      method: "DELETE", headers: { Authorization: `Bearer ${ownerToken}` }, cache: "no-store",
      signal: AbortSignal.timeout(15000),
    });
    if (!response.ok && response.status !== 401) throw new Error("迟到授权的撤销未确认，请检查订单准备授权");
  },
  listDrafts: (requestKey) => api.get("/api/order-drafts", { params: requestKey ? { requestKey } : {} }),
  getDraft: (id) => api.get(`/api/order-drafts/${encodeURIComponent(id)}`),
  confirmDraft: (id, data) => api.post(`/api/order-drafts/${encodeURIComponent(id)}/confirm`, data),
  cancelDraft: (id, version) => api.post(`/api/order-drafts/${encodeURIComponent(id)}/cancel`, { version }),
  getUserProfile: (userId) => api.get("/api/user/profile", { params: { userId } }),
  updateUserProfile: (data) => api.put("/api/user/profile", data),
  updateProfileDetails: (data) => api.put("/api/user/profile/details", data),
  activateWallet: (data) => api.post("/api/auth/activate-wallet", data),
  getWalletData: (userId) => api.get(`/api/wallet/${encodeURIComponent(userId)}`),
  getRechargeCard: (userId, cardKey) => api.post("/api/wallet/recharge", {
    userId, cardId: typeof cardKey === "string" ? cardKey : cardKey?.cardKey || "",
  }),
  getUserTransactions: (userId) => api.get("/api/transactions", { params: { userId } }),
  exchangePoints: (userId, points) => api.post("/api/wallet/exchange", { userId, points }),
  getMedicines: (name) => api.get("/api/medicines", { params: name ? { name } : {} }),
  submitOrder: (data, requestKey) => api.post("/api/orders", data, {
    headers: { "Idempotency-Key": requestKey },
  }),
  searchOrders: (criteria) => api.get("/api/orders", { params: criteria }),
  deleteOrder: (orderId) => api.delete(`/api/orders/${encodeURIComponent(orderId)}`),
};
