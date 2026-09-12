<script setup lang="ts">
import { connection } from '@/api/client'

const mode = '无'
const runningApps = 0
</script>

<template>
  <footer class="app-status">
    <span>当前模式：{{ mode }}</span>
    <span>运行中应用：{{ runningApps }}</span>
    <span>core：{{ connection.online ? '在线' : '离线（降级）' }}</span>
    <span>sidecar：阶段1 未接入指标</span>
  </footer>
</template>
