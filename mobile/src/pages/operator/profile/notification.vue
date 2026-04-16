<template>
  <view class="page theme-operator">
    <NavBar title="消息中心" bg-color="#2f855a" :show-back="true" />
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
  background: var(--operator-bg, #eef5ef);
}
</style>
