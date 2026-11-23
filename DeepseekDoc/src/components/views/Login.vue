<script setup>
import { ref, onMounted } from 'vue'
import { User, Lock } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/userStore'
import { ElMessage } from 'element-plus'

const userStore = useUserStore()
const router = useRouter()
const route = useRoute()
const formRef = ref()
const isShow = ref(false)
const form = ref({
    userId: '',
    password: ''
})

// 页面加载时触发动画
onMounted(() => {
    if (userStore.token) {
        router.replace('/logout')
    } else {
        setTimeout(() => isShow.value = true, 100)
    }
});

const validateForm = async () => {
    try {
        await userStore.login({
            userId: form.value.userId,
            password: form.value.password
        });
        const redirectPath = route.query.redirect || '/main';
        router.push(redirectPath);
    } catch (error) {
        ElMessage.error('登录失败，请检查用户名和密码')
    }
}
</script>

<template>
    <div class="login-container">
        <transition name="slide-up">
            <div v-show="isShow" class="login-box">
                <h1 class="title">欢迎使用 Deepseek家庭医生</h1>

                <el-form ref="formRef" :model="form" class="demo-form">
                    <el-form-item prop="userId">
                        <el-input v-model="form.userId" :prefix-icon="User" placeholder="请输入用户名" size="large" />
                    </el-form-item>

                    <el-form-item prop="password">
                        <el-input v-model="form.password" :prefix-icon="Lock" type="password" placeholder="请输入密码"
                            size="large" show-password />
                    </el-form-item>

                    <div class="action-group">
                        <el-button type="primary" size="large" class="submit-btn" @click="validateForm">
                            立即登录
                        </el-button>

                        <div class="link-text">
                            没有账号？
                            <el-link type="primary" :underline="never" @click="router.push('/register')">立即注册</el-link>
                        </div>
                    </div>
                </el-form>
            </div>
        </transition>
    </div>
</template>

<style scoped>
.login-container {
    height: 60vh;
    display: flex;
    align-items: center;
    justify-content: center;
}

.login-box {
    width: 24rem;
    /* w-96 */
    padding: 2rem;
    /* p-8 */
    border-radius: 0.5rem;
    /* rounded-lg */
    box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
    /* shadow-lg */
    background: rgba(255, 255, 255, 0.95);
    backdrop-filter: blur(10px);
    transform-origin: center;
}

.title {
    font-size: 1.5rem;
    /* text-2xl */
    font-weight: bold;
    /* font-bold */
    text-align: center;
    /* text-center */
    margin-bottom: 2rem;
    /* mb-8 */
    color: #2c3e50;
}

.demo-form>*:not(:last-child) {
    margin-bottom: 1.5rem;
    /* 1.5rem = 24px */
}

:deep(.el-input__wrapper) {
    border-radius: 12px !important;
}

.action-group {
    display: flex;
    flex-direction: column;
    align-items: center;
    /* space-y-4: add margin-bottom to all children except last */
}

.action-group>*:not(:last-child) {
    margin-bottom: 1rem;
    /* 1rem = 16px */
}

.submit-btn {
    width: 100%;
    /* w-full */
    border-radius: 12px;
    transition: all 0.3s ease;
}

.link-text {
    font-size: 0.875rem;
    /* text-sm */
    color: #6b7280;
    /* text-gray-500 */
}

/* 入场动画 */
.slide-up-enter-active {
    transition: all 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.slide-up-enter-from {
    opacity: 0;
    transform: translateY(100px);
}
</style>