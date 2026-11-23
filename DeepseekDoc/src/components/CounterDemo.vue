<template>
  <div class="counter-demo">
    <h1>{{ count }}</h1>
    <button @click="increment">增加</button>
  </div>
</template>

<script>
export default {
  data() {
    return {
      count: 0
    }
  },
  methods: {
    increment() {
      this.count += 1; 
    }
  }
}
</script>

<style scoped>
.counter-demo {
  text-align: center;
  margin: 2rem;
}
button {
  padding: 8px 16px;
  font-size: 1rem;
  cursor: pointer;
}
</style>