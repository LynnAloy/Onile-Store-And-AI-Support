// @/stores/orderStore.js
import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { useRouter } from "vue-router";
import API from "@/components/api";
import { useMedicineStore } from "./medicineStore";
import { useUserStore } from "./userStore";
import { useWalletStore } from "./walletStore";
import { ElMessage, ElMessageBox } from "element-plus";
import { paymentsEnabled, createPaymentClient } from "@/services/paymentClient.mjs";

export const useOrderStore = defineStore("order", () => {
  const router = useRouter();
  const medicineStore = useMedicineStore();
  const userStore = useUserStore();
  const walletStore = useWalletStore();

  // 订单状态
  const cart = ref([]);
  const orders = ref([]);
  const currentOrder = ref(null);
  const orderStatus = ref("idle"); // idle, pending, success, failed
  const orderError = ref(null);
  const checkoutKey = ref("");
  const checkoutPayload = ref("");

  const orderForm = ref({
    recipientName: "",
    recipientPhone: "",
    recipientAddress: "",
    note: "",
  });

  window.addEventListener("auth-cleared", () => {
    cart.value = [];
    orders.value = [];
    currentOrder.value = null;
    orderStatus.value = "idle";
    orderError.value = null;
    checkoutKey.value = "";
    checkoutPayload.value = "";
    orderForm.value = {
      recipientName: "", recipientPhone: "", recipientAddress: "", note: "",
    };
    submitResult.value = { success: false, orderId: "", points: 0, newBalance: 0 };
  });

   const submitResult = ref({
    success: false,
    orderId: "",
    points: 0,
    newBalance: 0,
  });

  // 计算属性
  const hasPendingOrder = computed(() => orderStatus.value === "pending");
  const orderHistory = computed(() => orders.value);
  const totalOrders = computed(() => orders.value.length);
  const totalPrice = computed(() => {
    return cart.value.reduce((total, item) => {
      return total + item.price * item.quantity;
    }, 0);
  });
  
  const infoRules = {
    recipientName: [{ required: true, message: "请输入收货人姓名", trigger: "blur" }],
    recipientPhone: [
      { required: true, message: "请输入联系电话", trigger: "blur" },
      {
        pattern: /^1[3-9]\d{9}$/,
        message: "请输入有效的手机号码",
        trigger: "blur",
      },
    ],
    recipientAddress: [{ required: true, message: "请输入收货地址", trigger: "blur" }],
    note: [],
  };

  function addToCart(med) {
    const stockItem = medicineStore.getMedicineById(med.id);
    if (!stockItem || stockItem.stock < 1) {
      return ElMessage.warning(`${med.name} 库存不足`);
    }
    medicineStore.updateTempStock(med.id, -1);

    const exist = cart.value.find((it) => it.id === med.id);
    if (exist) {
      exist.quantity++;
    } else {
      cart.value.push({
        id: med.id,
        name: med.name,
        price: med.price,
        quantity: 1,
      });
    }
  }

  function removeFromCart(item) {
    const idx = cart.value.findIndex((it) => it.id === item.id);
    if (idx > -1) {
      medicineStore.updateTempStock(item.id, item.quantity);
      cart.value.splice(idx, 1);
    }
  }

  function updateItemQuantity(item, oldQty, newQty) {
    const delta = newQty - oldQty;
    const stockItem = medicineStore.getMedicineById(item.id);
    if (!stockItem) {
      return ElMessage.warning("药品不存在");
    }
    if (delta > 0 && stockItem.tempStock < delta) {
      ElMessage.warning(`${item.name} 可用库存不足 (剩余: ${stockItem.tempStock})`);
      medicineStore.updateTempStock(item.id, -stockItem.tempStock);
      item.quantity = oldQty + stockItem.tempStock;
      return;
    }
    medicineStore.updateTempStock(item.id, -delta);
    item.quantity = newQty;
  }

  const clearCart = () => {
    cart.value = [];
  };

  // 提交订单
  async function submitOrder() {
    if (paymentsEnabled) {
      ElMessage.info("请先准备并确认草稿，再进入独立付款页面");
      return router.push("/drafts");
    }
    if (orderStatus.value === "pending") return;
    if (!userStore.isHealthWalletActive) {
      ElMessage.warning("请先激活健康钱包");
      return router.push("/activate");
    }
    if (!cart.value.length) {
      orderError.value = "购物车为空，无法提交订单";
      orderStatus.value = "failed";
      return;
    }
    if (walletStore.balance < totalPrice.value) {
      ElMessage.warning("余额不足，请充值");
      orderStatus.value = "failed";
      return router.push("/charge");
    }

    let walletPassword;
    try {
      const result = await ElMessageBox.prompt("请输入六位支付密码以确认本次购买", "确认支付", {
        inputType: "password",
        inputPattern: /^[0-9]{6}$/,
        inputErrorMessage: "支付密码必须是六位数字",
        confirmButtonText: "确认支付",
        cancelButtonText: "取消",
      });
      walletPassword = result.value;
    } catch {
      return;
    }
    orderStatus.value = "pending";
    orderError.value = null;

    try {
      const payload = {
        userId:   userStore.userId,
        recipientName:     orderForm.value.recipientName,
        recipientPhone:    orderForm.value.recipientPhone,
        recipientAddress:  orderForm.value.recipientAddress,
        note:     orderForm.value.note,
        items:    cart.value.map((it) => ({
          medicineId: it.id,
          quantity:   it.quantity,
        })),
      };

      const serialized = JSON.stringify(payload);
      if (checkoutPayload.value !== serialized || !checkoutKey.value) {
        checkoutKey.value = crypto.randomUUID();
        checkoutPayload.value = serialized;
      }
      const result = await API.submitOrder({ ...payload, walletPassword }, checkoutKey.value);
      const { orderId, points, newBalance, totalPoints } = result;

      // 构造当前订单记录
      currentOrder.value = {
        id:          orderId,
        timestamp:   new Date().toISOString(),
        items:       [...cart.value],
        totalPrice:  totalPrice.value,
        earnedPoints: points,
      };

      // 更新本地库存和钱包数据
      walletStore.updateAfterOrder(newBalance, totalPoints);
      await medicineStore.fetchMedicines();

      orders.value.unshift(currentOrder.value);
      clearCart();
      checkoutKey.value = "";
      checkoutPayload.value = "";

      submitResult.value = {
        success:   true,
        orderId,
        points,
        newBalance,
      };

      orderStatus.value = "success";
      router.push("/shoppingsuccess");
    } catch (err) {
      console.error("订单提交失败:", err);
      orderError.value  = err.message || "订单提交失败，请重试";
      orderStatus.value = "failed";
      router.push("/shoppingfail");
    }
  }

  async function searchOrders(phone = "") {
    const owner = { userId: userStore.userId, token: userStore.token };
    const current = () => owner.userId === userStore.userId && owner.token === userStore.token;
    try {
      const params = phone
        ? { phone }
        : { userId: userStore.userId };

      const result = paymentsEnabled
        ? await createPaymentClient({ baseURL: import.meta.env.VITE_API_BASE || "" }).list(owner, phone)
        : await API.searchOrders(params);
      if (!current()) return [];
      if (!result.length) {
        ElMessage.warning("未找到相关订单");
      }
      orders.value = result;
      return result;
    } catch (err) {
      if (!current()) return [];
      console.error("搜索订单失败:", err);
      orderError.value = err.message || "搜索订单失败";
      return [];
    }
  }

  async function deleteOrder(orderId) {
    try {
      await API.deleteOrder(orderId);
      orders.value = orders.value.filter((o) => o.id !== orderId);
      if (currentOrder.value?.id === orderId) {
        currentOrder.value = null;
      }
      return true;
    } catch (err) {
      console.error("删除订单失败:", err);
      orderError.value = err.message || "删除订单失败";
      return false;
    }
  }

  const getOrderDetails = (orderId) => {
    return orders.value.find((order) => order.id === orderId) || null;
  };

  return {
    // 状态
    cart,
    orders,
    currentOrder,
    orderStatus,
    orderError,
    orderForm,
    infoRules,
    submitResult,

    // 计算属性
    hasPendingOrder,
    orderHistory,
    totalOrders,
    totalPrice,

    // 操作方法
    submitOrder,
    searchOrders,
    deleteOrder,
    getOrderDetails,
    addToCart,
    removeFromCart,
    clearCart,
    updateItemQuantity,
  };
});
