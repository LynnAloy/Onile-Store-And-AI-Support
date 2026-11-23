<script setup>
import { ref, computed } from "vue";
import { useRouter } from "vue-router";
import { Lock } from "@element-plus/icons-vue";
import { useUserStore } from "@/stores/userStore";
import { useWalletStore } from "@/stores/walletStore";

const router = useRouter();
const userStore = useUserStore();
const walletStore = useWalletStore();

const formRef = ref(null);
const isShow = ref(false);

const formModel = computed(() => ({
  password: walletStore.walletPassword,
  confirmPassword: walletStore.confirmPassword,
  agree: walletStore.agreedToTerms,
}))

// 密码验证规则
const validatePass = (rule, value, callback) => {
  if (value === "") {
    callback(new Error("请输入密码"));
  } else if (!/^[0-9]{6}$/.test(value)) {
    callback(new Error("支付密码必须是六位数字"));
  } else {
    if (walletStore.confirmPassword !== "") {
      formRef.value.validateField("confirmPassword");
    }
    callback();
  }
};

// 确认密码验证
const validatePass2 = (rule, value, callback) => {
  if (value === "") {
    callback(new Error("请再次输入密码"));
  } else if (value !== walletStore.walletPassword) {
    callback(new Error("两次输入密码不一致!"));
  } else {
    callback();
  }
};

// 表单规则
const rules = {
  password: [{ validator: validatePass, trigger: "blur" }],
  confirmPassword: [{ validator: validatePass2, trigger: "blur" }],
  agree: [
    {
      validator: (rule, value, callback) => {
        return value ? callback() : callback(new Error());
      },
      trigger: "change",
    },
  ],
};

const activateWallet = async () => {
  try{
    await formRef.value.validate();
    await userStore.activateHealthWallet(walletStore.walletPassword);
    router.push("/charge");
  }catch(error){
    console.error("激活钱包失败：", error.message);
  }
};

setTimeout(() => (isShow.value = true), 100);
</script>

<template>
  <div class="activate-container">
    <transition name="slide-up">
      <el-card class="activate-card" shadow="hover" v-show="isShow">
        <h2 class="title">激活健康钱包</h2>

        <el-form :model="formModel" :rules="rules" ref="formRef">
          <!-- 密码设置 -->
          <el-form-item prop="password">
            <el-input :model-value="walletStore.walletPassword" @update:model-value="v => walletStore.walletPassword = v" :prefix-icon="Lock" type="password" placeholder="设置六位数字支付密码" show-password />
          </el-form-item>

          <!-- 确认密码 -->
          <el-form-item prop="confirmPassword">
            <el-input v-model="walletStore.confirmPassword" :prefix-icon="Lock" type="password" placeholder="确认密码" show-password />
          </el-form-item>

          <!-- 协议确认 -->
          <el-form-item prop="agree">
            <el-checkbox v-model="walletStore.agreedToTerms">
              我已阅读并同意
              <el-link type="primary" underline="never">《健康钱包服务协议》</el-link>
            </el-checkbox>
          </el-form-item>

          <!-- 提交按钮 -->
          <el-button type="primary" class="submit-btn" :disabled="!walletStore.agreedToTerms" @click="activateWallet">立即激活</el-button>
        </el-form>
      </el-card>
    </transition>
  </div>
</template>

<style scoped>
.slide-up-enter-active {
  transition: all 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.slide-up-enter-from {
  opacity: 0;
  transform: translateY(100px);
}

.activate-container {
  min-height: 60vh;
  display: flex;
  justify-content: center;
  align-items: center;
  background: #ffffff;
  margin: 10px 0px 100px 0px;
  border: none;
}

.activate-card {
  width: 400px;
  padding: 30px;
}

.title {
  text-align: center;
  margin-bottom: 30px;
  color: #409eff;
}

.el-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.submit-btn {
  width: 100%;
  margin-top: -10px;
  font-size: 16px;
}
</style>
