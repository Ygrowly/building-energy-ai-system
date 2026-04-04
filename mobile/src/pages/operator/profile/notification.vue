<template>
  <view class="page">
    <NavBar title="消息中心" bg-color="#1a1a2e" :show-back="true" />
    <OperatorMessageCenter />
  </view>
</template>

<script setup lang="ts">
import NavBar from '../../../components/NavBar.vue'
import OperatorMessageCenter from '../../../components/OperatorMessageCenter.vue'
import { useRouteGuard } from '../../../utils/route-guard'
import { OPERATOR_ROLES } from '../../../constants/roles'

useRouteGuard(OPERATOR_ROLES)
</script>

<style lang="scss" scoped>
.page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f0f2f8;
}
</style>
