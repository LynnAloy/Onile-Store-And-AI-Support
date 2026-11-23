// src/stores/walletStore.js
import { defineStore } from "pinia";
import { ref } from "vue";
import { ElMessage } from "element-plus"; // 引入 Element Plus 的消息提示组件
import API from "@/components/api";
import { useUserStore } from "./userStore"; 

export const useWalletStore = defineStore("wallet", () => {
  // 状态
  const balance = ref(0);
  const points = ref(0);
  const transactions = ref([]);
  const walletPassword = ref("");
  const confirmPassword = ref("");
  const agreedToTerms = ref(false);
  const userStore = useUserStore(); 
  
  //fetch data
  const fetchWalletData = async () => {
    try {
      const data = await API.getWalletData(userStore.userId);
      balance.value = data.balance ?? 0;
      points.value = data.points ?? 0;
      transactions.value = data.transactions ?? [];
    } catch (err) {
      ElMessage.error("获取钱包数据失败");
      throw err;
    }
  }

  async function recharge(userId, cardKey) {
    try {
      const { newBalance, amount } = await API.getRechargeCard(userId, cardKey);
      balance.value = newBalance;
      transactions.value.unshift({
        id: `tx_${Date.now()}`,
        type: "充值",
        amount,
        date: new Date().toISOString(),
      });
      return { newBalance, amount };
    } catch (err) {
      ElMessage.error("充值失败");
      throw err;
    }
  }


  async function exchangePoints(userId, pointsToExchange) {
    try {
      if (pointsToExchange > points.value) {
        throw new Error("积分不足");
      }
      const { newPoints, newBalance } = await API.exchangePoints(
        userId,
        pointsToExchange
      );
      points.value = newPoints;
      balance.value = newBalance;
      transactions.value.unshift({
        id: `tx_${Date.now()}`,
        type: "积分兑换",
        points: pointsToExchange,
        amount: Math.floor(pointsToExchange / 10),
        date: new Date().toISOString(),
      });
      return { newPoints, newBalance };
    } catch (err) {
      console.error("积分兑换失败:", err);
      ElMessage.error("积分兑换失败");
      throw err;
    }
  }

  function updateAfterOrder(newBalance, newPoints) {
    balance.value = newBalance;
    points.value = newPoints;
  }


  const clearWalletPassword = () => {
    walletPassword.value = "";
  };

  function clearWalletData() {
    walletPassword.value = "";
    confirmPassword.value = "";
    agreedToTerms.value = false;
    transactions.value = [];
    balance.value = 0;
    points.value = 0;
  }

  return {
    balance,
    points,
    transactions,
    walletPassword,
    confirmPassword,
    agreedToTerms,
    clearWalletData,
    fetchWalletData,
    recharge,
    exchangePoints,
    updateAfterOrder,
    clearWalletPassword,
  };
});
