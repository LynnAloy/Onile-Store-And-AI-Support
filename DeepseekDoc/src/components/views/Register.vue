<script setup>
import { ref, onMounted } from "vue";
import { useRouter } from "vue-router";
import API from "@/components/api/index.js";
import { ElMessage } from "element-plus";
import { User, Lock } from "@element-plus/icons-vue";
import { useUserStore } from "@/stores/userStore";

const router = useRouter();
const userStore = useUserStore();

const formRef = ref(null);
const isShow = ref(false);
const form = ref({
  userId: "",
  password: "",
  confirmPassword: "",
});

const rules = {
  userId: [
    { required: true, message: "请输入用户名", trigger: "blur" },
    { pattern: /^[A-Za-z0-9_-]{3,40}$/, message: "用户名为3-40位字母、数字、下划线或连字符", trigger: "blur" },
  ],
  password: [
    { required: true, message: "请输入密码", trigger: "blur" },
    { min: 8, max: 64, message: "密码长度8-64位", trigger: "blur" },
  ],
  confirmPassword: [
    { required: true, message: "请确认密码", trigger: "blur" },
    {
      validator: (rule, value, callback) => {
        if (value !== form.value.password) {
          callback(new Error("两次输入密码不一致"));
        } else {
          callback();
        }
      },
      trigger: "blur",
    },
  ],
};

onMounted(() => {
  setTimeout(() => (isShow.value = true), 100);
});

const handleRegister = async () => {
  await formRef.value.validate();
  try {
    await userStore.register({
      userId: form.value.userId,
      password: form.value.password,
    });
    ElMessage.success("注册成功，请登录");
  } catch (e) {
  }
};
</script>

<template>
  <div class="register-container">
    <transition name="slide-up">
      <div v-show="isShow" class="register-box" shadow="hover">
        <h1 class="title">注册</h1>
        <el-form :model="form" :rules="rules" ref="formRef" class="register-form">
          <el-form-item prop="userId">
            <el-input
              v-model="form.userId"
              :prefix-icon="User"
              placeholder="请输入用户名"
              size="large"
              clearable
            />
          </el-form-item>
          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              :prefix-icon="Lock"
              type="password"
              placeholder="请输入密码"
              size="large"
              show-password
              clearable
            />
          </el-form-item>
          <el-form-item prop="confirmPassword">
            <el-input
              v-model="form.confirmPassword"
              :prefix-icon="Lock"
              type="password"
              placeholder="请确认密码"
              size="large"
              show-password
              clearable
            />
          </el-form-item>
          <div class="action-group">
            <el-button type="primary" size="large" class="submit-btn" @click="handleRegister">
              注册
            </el-button>
            <div class="link-text">
              已有账号？
              <el-link type="primary" :underline="never" @click="router.push('/login')">去登录</el-link>
            </div>
          </div>
        </el-form>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.register-container {
  height: 60vh;
  display: flex;
  align-items: center;
  justify-content: center;
  margin:0px 0px 20px 0px;
}

.register-box {
  width: 24rem;
  padding: 2rem;
  border-radius: 0.5rem;
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  transform-origin: center;
}

.title {
  font-size: 1.5rem;
  font-weight: bold;
  text-align: center;
  margin-bottom: 2rem;
  color: #2c3e50;
}

.register-form > *:not(:last-child) {
  margin-bottom: 1.5rem;
}

:deep(.el-input__wrapper) {
  border-radius: 12px !important;
}

.action-group {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.action-group > *:not(:last-child) {
  margin-bottom: 1rem;
}

.submit-btn {
  width: 100%;
  border-radius: 12px;
  transition: all 0.3s ease;
}

.link-text {
  font-size: 0.875rem;
  color: #6b7280;
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
