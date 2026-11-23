// @/stores/userStore.js
import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { useRouter } from "vue-router";
import API from "@/components/api";
import { useWalletStore } from "./walletStore";
import { ElMessage } from "element-plus";
import { emptyHealthProfile, profilePayload } from "@/services/profilePayload.mjs";

export const useUserStore = defineStore("user", () => {
  const router = useRouter();
  const walletStore = useWalletStore();

  const token = ref(localStorage.getItem("token") || "");
  const healthToken = ref(localStorage.getItem("healthToken") || "");
  const userId = ref(localStorage.getItem("userId") || "");
  const userInfo = ref({
    nickname: `用户${Math.floor(Math.random() * 90000 + 10000)}`,
    avatar: "",
    email: "",
  });
  const healthProfile = ref(emptyHealthProfile());

  // getters
  const isLoggedIn = computed(() => !!token.value);
  const isHealthWalletActive = computed(() => !!healthToken.value);
  const fullUserInfo = computed(() => ({
    ...userInfo.value,
    ...healthProfile.value,
  }));

  function clearPrivateState() {
    walletStore.clearWalletData();
    userInfo.value = { nickname: "", avatar: "", email: "" };
    healthProfile.value = emptyHealthProfile();
    window.dispatchEvent(new Event("auth-cleared"));
  }

  window.addEventListener("auth-expired", () => {
    token.value = "";
    userId.value = "";
    healthToken.value = "";
    localStorage.removeItem("userId");
    clearPrivateState();
    router.replace("/login");
  });

  async function register({ userId: uid, password }) {
    try {
      const { success } = await API.register({ userId: uid, password });
      if (success) {
        await router.push("/login");
      }
      return success;
    } catch (err) {
      ElMessage.error("注册失败：" + (err.message || ""));
      console.error("注册失败：", err);
      throw err;
    }
  }

  // actions
  async function login({ userId: uid, password }) {
    const raw = await API.login({ userId: uid, password });
    // 再解构出 token 和后端返回的 userId
    const { token: t, userId: id } = raw;
    clearPrivateState();
    healthToken.value = raw.walletActivated ? "wallet-active" : "";
    localStorage.setItem("healthToken", healthToken.value);
    token.value = t;
    userId.value = id;
    localStorage.setItem("token", token.value);
    localStorage.setItem("userId", userId.value);
    // 拉钱包时用正确的变量 id
    try {
      await walletStore.fetchWalletData(id);
    } catch (e) {
      console.error("wallet fetch error:", e);
      ElMessage.error("获取钱包数据失败");
    }
    try {
      await fetchUserProfile();
    } catch (e) {
      console.error("wallet fetch error:", e);
      ElMessage.error("获取用户资料失败");
    }
  }

  //这是注销而非登出 登出是切换用户 而这里清空了数据
  const logout = async () => {
    const originalToken = token.value;
    if (!originalToken) return;
    try {
      await API.logout(userId.value, originalToken);
    } catch {}
    if (token.value !== originalToken || localStorage.getItem("token") !== originalToken) return;
    token.value = "";
    userId.value = "";
    healthToken.value = "";
    localStorage.removeItem("token");
    localStorage.removeItem("userId");
    localStorage.removeItem("healthToken");
    clearPrivateState();
    router.push("/login");
    return true;
  };

  async function activateHealthWallet(password) {
    const { healthToken: ht } = await API.activateWallet({
      userId: userId.value,
      password,
    });
    healthToken.value = ht;
    localStorage.setItem("healthToken", healthToken.value);
    walletStore.clearWalletPassword();
    walletStore.confirmPassword = "";
  }

  async function fetchUserProfile() {
    if (!token.value) return;
    const profile = await API.getUserProfile(userId.value);
    userInfo.value = {
      nickname: profile.nickname || userId.value,
      avatar: profile.avatar || "",
      email: profile.email || "",
    };
    healthProfile.value = {
      ...emptyHealthProfile(), ...profile, medical: profile.medicalHistory || [],
    };
    healthToken.value = profile.walletActivated ? "wallet-active" : "";
    localStorage.setItem("healthToken", healthToken.value);
  }

  async function updateUserProfile() {
    try {
      const payload = profilePayload(userId.value, userInfo.value, healthProfile.value);
      await API.updateProfileDetails(payload);
      window.dispatchEvent(new Event("profile-context-changed"));
      await fetchUserProfile();
      ElMessage.success("个人资料与授权选择已保存");
      return true;
    } catch (error) {
      ElMessage.error("保存失败：" + error.message);
      return false;
    }
  }

  return {
    token,
    healthToken,
    userInfo,
    healthProfile,
    userId,
    isLoggedIn,
    isHealthWalletActive,
    fullUserInfo,
    register,
    login,
    logout,
    activateHealthWallet,
    fetchUserProfile,
    updateUserProfile,
  };
});
