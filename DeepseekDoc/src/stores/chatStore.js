// src/stores/chatStore.js
import { defineStore } from "pinia";
import { ref, nextTick } from "vue";
import { ElMessage } from "element-plus";

export const useChatStore = defineStore("chat", () => {
  // 状态
  const chatList = ref(null);
  const messages = ref([
    { sender: "bot", text: "你好！有什么可以帮到您？", ico: "bot", show: true },
    { sender: "user", text: "你好，我想了解一些信息。", ico: "user", show: false },
    { sender: "user", text: "你好，我想了解一些信息。", ico: "user", show: true },
    { sender: "bot", text: "请问您想了解哪方面的信息呢？", ico: "bot", show: true },
    { sender: "user", text: "你好，我想了解一些信息。", ico: "user", show: false },
    { sender: "bot", text: "请问您想了解哪方面的信息呢？", ico: "bot", show: false },
  ]);
  
  const inputText = ref("");
  const isBotTyping = ref(false);
  const showName = ref("智能问诊平台");

  // 方法
  function sendMessage() {
    if (!localStorage.getItem("token")) {
      ElMessage.error("请先登录！");
      return;
    }
    if (inputText.value.trim()) {
      const text = inputText.value;
      inputText.value = "";
      addMessage("user", text);

      isBotTyping.value = true;

      setTimeout(() => {
        addMessage("bot", "您说的是：" + text);
        isBotTyping.value = false;
      }, 500);
    }
  }

  function addMessage(sender, text) {
    messages.value.push({
      sender,
      text,
      ico: sender === "user" ? "user" : "bot",
      show: true,
    });

    nextTick(() => {
      if (chatList.value?.wrapRef) {
        chatList.value.wrapRef.scrollTop = chatList.value.wrapRef.scrollHeight;
      }
    });
  }

  function setShowName(name) {
    showName.value = name;
  }

  return {
    chatList,
    messages,
    inputText,
    isBotTyping,
    showName,
    sendMessage,
    addMessage,
    setShowName
  };
});