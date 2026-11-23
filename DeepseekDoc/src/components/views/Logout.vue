<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { CircleCheck } from '@element-plus/icons-vue'
import { useUserStore} from '@/stores/userStore'
import { ElMessage } from 'element-plus'

const router = useRouter()
const isShow = ref(false)
const userStore = useUserStore()
const userName = userStore.userInfo.nickname;

// 执行登出操作
const performLogout = async() => {
  try{
    if (await userStore.logout()) {
      router.replace({ path: '/login', query: { from: 'logout'} });
    }
  }catch(error){
    ElMessage.error('登出失败，请重试');
  }
}

setTimeout(() => isShow.value = true, 100)
</script>

<template>
    <div class="logout-container">
        <transition name="slide-up">
            <div v-show="isShow" class="logout-box">
                <h1 class="title">Deepseek家庭医生</h1>
                <div class="logout-content">
                    <el-icon class="logout-icon">
                        <CircleCheck />
                    </el-icon>
                    <h3>你好，{{ userName }}</h3>
                    <el-button type="primary" class="logout-btn" @click="performLogout">
                        登出
                    </el-button>
                </div>
            </div>
        </transition>
    </div>
</template>

<style scoped>
.logout-container {
    height: 80vh;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #ffffff;
}

.logout-box {
    width: 400px;
    padding: 2.5rem;
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.95);
    box-shadow: 0 12px 24px rgba(0, 0, 0, 0.1);
    text-align: center;
}

.logout-content {
    margin: 2rem 0;
}

.logout-icon {
    font-size: 4rem;
    color: #67C23A;
    margin-bottom: 1.5rem;
}

.title {
    color: #2c3e50;
    font-size: 1.8rem;
    margin-bottom: 1.5rem;
}

h3 {
    color: #409EFF;
    margin: 1rem 0;
}

p {
    color: #909399;
    font-size: 0.9rem;
}

.logout-btn{
    width:60%;
    margin-top: 2rem;
    border-radius: 12px;
}

/* 保持原有动画 */
.slide-up-enter-active {
    transition: all 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.slide-up-enter-from {
    opacity: 0;
    transform: translateY(100px);
}
</style>
