<script setup>
import { useRouter } from 'vue-router';
import { ref, onMounted } from 'vue';
import { useUserStore } from '@/stores/userStore';
import { useOrderStore } from '@/stores/orderStore';

const isShow = ref(false)
const router = useRouter()
const orderStore = useOrderStore()
const userStore = useUserStore()

setTimeout(() => isShow.value = true, 100)

onMounted(() => {
  if(!userStore.healthToken) {
    setTimeout(() => router.push('/activate'), 3000)
  } else {
    setTimeout(() => router.push('/charge'), 3000)
  }
})
</script>

<template>
  <div class="fail-container">
    <transition name="slide-up">
    <div class="fail-box" v-show="isShow">
      <el-icon class="fail-icon"><CircleClose /></el-icon>
      <h2>订单提交失败</h2>
      <p>3秒后跳转到{{ userStore.healthToken ? '充值页面' : '激活页面' }}</p>
    </div>
    </transition>
  </div>
</template>

<style scoped>
.fail-container {
  height: 60vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255,255,255,0.9);
  margin:0px 0px 100px 0px;
}

.fail-box {
  text-align: center;
  padding: 40px;
  border-radius: 12px;
  box-shadow: 0 12px 24px rgba(0,0,0,0.1);
}

.fail-icon {
  font-size: 80px;
  color: #F56C6C;
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