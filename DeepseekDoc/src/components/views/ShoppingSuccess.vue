<script setup>
import { useRouter } from 'vue-router'
import { ref } from 'vue'
import { useUserStore } from '@/stores/userStore'
import { useOrderStore } from '@/stores/orderStore'

const userStore = useUserStore()
const orderStore = useOrderStore()
const isShow = ref(false)
const router = useRouter()
const orderId = ref(orderStore.submitResult.orderId || "")
const earnedPoints = ref(orderStore.submitResult.points || 0)

setTimeout(() => isShow.value = true, 100)
</script>

<template>
  <div class="success-container">
    <transition name="slide-up">
    <div class="success-box" v-show="isShow">
      <el-icon class="success-icon"><CircleCheck /></el-icon>
      <h2>订单提交成功！</h2>
      <p>订单编号：{{ orderId }}</p>
      <p>获得健康积分：+{{ earnedPoints }}</p>
      <el-button type="primary" @click="router.push('/main')">返回首页</el-button>
    </div>
    </transition>
  </div>
</template>

<style scoped>
.success-container {
  height: 60vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255,255,255,0.9);
  margin:0px 0px 100px 0px;
}

.success-box {
  text-align: center;
  padding: 40px;
  border-radius: 12px;
  box-shadow: 0 12px 24px rgba(0,0,0,0.1);
}

.success-icon {
  font-size: 80px;
  color: #67C23A;
  margin-bottom: 20px;
}

.slide-up-enter-active {
    transition: all 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.slide-up-enter-from {
    opacity: 0;
    transform: translateY(100px);
}
</style>