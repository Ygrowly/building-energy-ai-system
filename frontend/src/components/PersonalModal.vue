<template>
  <Teleport to="body">
    <Transition name="modal-fade">
      <div v-if="visible" class="pm-overlay" @click.self="$emit('close')">
        <div class="pm-dialog" :class="'section-' + activeSection">
          <!-- 标题栏 -->
          <div class="pm-header">
            <h2 class="pm-title">{{ SECTION_TITLES[activeSection] }}</h2>
            <button class="pm-close" @click="$emit('close')">
              <Icon icon="mdi:close" width="18" />
            </button>
          </div>

          <!-- 内容区 -->
          <div class="pm-body" :class="{ 'has-sidebar': activeSection === 'settings' }">

            <!-- ═══════════ 设置（Grok 风格：左侧Tab + 右侧内容）═══════════ -->
            <template v-if="activeSection === 'settings'">
              <!-- 左侧竖向Tab -->
              <nav class="settings-sidebar">
                <button
                  v-for="tab in SETTINGS_TABS"
                  :key="tab.id"
                  class="sidebar-tab"
                  :class="{ active: settingsTab === tab.id }"
                  @click="settingsTab = tab.id"
                >
                  <Icon :icon="tab.icon" width="16" />
                  <span>{{ tab.label }}</span>
                </button>
              </nav>

              <!-- 右侧内容 -->
              <div class="settings-content">

                <!-- 个人资料 -->
                <template v-if="settingsTab === 'profile'">
                  <!-- 个人信息头部 -->
                  <div class="profile-header">
                    <div
                      class="profile-avatar-wrap"
                      @click="triggerAvatarUpload"
                      title="点击更换头像"
                    >
                      <img v-if="avatarUrl" :src="avatarUrl" class="profile-avatar-img" alt="头像" />
                      <div v-else class="profile-avatar-placeholder">
                        <span class="avatar-initials">{{ avatarInitials }}</span>
                      </div>
                      <div class="avatar-overlay">
                        <Icon icon="mdi:camera-outline" width="16" />
                        <span>更换</span>
                      </div>
                    </div>
                    <div class="profile-header-info">
                      <div class="profile-name-row">
                        <p class="profile-username">{{ user?.username ?? '—' }}</p>
                        <span class="role-badge" :class="'role-' + (user?.role ?? 'resident')">
                          {{ ROLE_LABELS[user?.role ?? 'resident'] ?? user?.role }}
                        </span>
                      </div>
                      <p class="profile-email-hint">{{ user?.email || '未设置邮箱' }}</p>
                    </div>
                    <input
                      ref="avatarInputRef"
                      type="file"
                      accept="image/*"
                      class="avatar-file-input"
                      @change="onAvatarChange"
                    />
                  </div>
                  <div class="profile-section-divider"></div>

                  <!-- 用户名 -->
                  <div class="grok-row">
                    <div class="grok-row-info">
                      <p class="grok-row-title">用户名</p>
                      <p class="grok-row-sub">{{ profileForm.username || '未设置' }}</p>
                    </div>
                    <div class="row-btns">
                      <button v-if="editingField === 'username'" class="btn-primary sm" @click="saveProfile" :disabled="profileSaving">
                        <Icon :icon="profileSaving ? 'mdi:loading' : 'mdi:check'" width="13" :class="{ spin: profileSaving }" />
                        {{ profileSaving ? '保存中...' : '保存' }}
                      </button>
                      <button class="btn-action" @click="editingField = editingField === 'username' ? '' : 'username'">
                        {{ editingField === 'username' ? '取消' : '更改' }}
                      </button>
                    </div>
                  </div>
                  <div v-if="editingField === 'username'" class="grok-edit-area">
                    <input v-model="profileForm.username" type="text" class="setting-input" placeholder="请输入用户名（2-50位，支持中英文）" />
                    <span v-if="profileMsg && editingField === 'username'" class="form-msg" :class="profileMsgType">{{ profileMsg }}</span>
                  </div>

                  <!-- 邮箱 -->
                  <div class="grok-row">
                    <div class="grok-row-info">
                      <p class="grok-row-title">邮箱</p>
                      <p class="grok-row-sub">{{ profileForm.email || '未设置' }}</p>
                    </div>
                    <div class="row-btns">
                      <button v-if="editingField === 'email'" class="btn-primary sm" @click="saveProfile" :disabled="profileSaving">
                        <Icon :icon="profileSaving ? 'mdi:loading' : 'mdi:check'" width="13" :class="{ spin: profileSaving }" />
                        {{ profileSaving ? '保存中...' : '保存' }}
                      </button>
                      <button class="btn-action" @click="editingField = editingField === 'email' ? '' : 'email'">
                        {{ editingField === 'email' ? '取消' : '更改' }}
                      </button>
                    </div>
                  </div>
                  <div v-if="editingField === 'email'" class="grok-edit-area">
                    <input v-model="profileForm.email" type="email" class="setting-input" placeholder="请输入邮箱" />
                    <span v-if="profileMsg && editingField === 'email'" class="form-msg" :class="profileMsgType">{{ profileMsg }}</span>
                  </div>

                  <!-- 手机号 -->
                  <div class="grok-row">
                    <div class="grok-row-info">
                      <p class="grok-row-title">手机号</p>
                      <p class="grok-row-sub">{{ profileForm.phone || '未设置' }}</p>
                    </div>
                    <div class="row-btns">
                      <button v-if="editingField === 'phone'" class="btn-primary sm" @click="saveProfile" :disabled="profileSaving">
                        <Icon :icon="profileSaving ? 'mdi:loading' : 'mdi:check'" width="13" :class="{ spin: profileSaving }" />
                        {{ profileSaving ? '保存中...' : '保存' }}
                      </button>
                      <button class="btn-action" @click="editingField = editingField === 'phone' ? '' : 'phone'">
                        {{ editingField === 'phone' ? '取消' : '更改' }}
                      </button>
                    </div>
                  </div>
                  <div v-if="editingField === 'phone'" class="grok-edit-area">
                    <input v-model="profileForm.phone" type="tel" class="setting-input" placeholder="请输入手机号" />
                    <span v-if="profileMsg && editingField === 'phone'" class="form-msg" :class="profileMsgType">{{ profileMsg }}</span>
                  </div>

                  <!-- 注册时间（只读） -->
                  <div class="grok-row">
                    <div class="grok-row-info">
                      <p class="grok-row-title">注册时间</p>
                      <p class="grok-row-sub">{{ formatDate(user?.created_at) }}</p>
                    </div>
                  </div>

                  <p class="grok-id">{{ user?.id }}</p>
                </template>

                <!-- 账号安全 -->
                <template v-if="settingsTab === 'security'">
                  <div class="grok-row">
                    <div class="grok-row-info">
                      <p class="grok-row-title">账号状态</p>
                      <p class="grok-row-sub">{{ user?.is_active ? '正常使用' : '已停用' }}</p>
                    </div>
                    <span class="status-dot" :class="user?.is_active ? 'ok' : 'warn'"></span>
                  </div>

                  <div class="grok-row">
                    <div class="grok-row-info">
                      <p class="grok-row-title">修改密码</p>
                      <p class="grok-row-sub">定期更换密码以保护账号安全</p>
                    </div>
                    <button class="btn-action" @click="showPwdForm = !showPwdForm">
                      {{ showPwdForm ? '取消' : '更改' }}
                    </button>
                  </div>

                  <div v-if="showPwdForm" class="grok-edit-area pwd-form">
                    <input v-model="pwdForm.old" type="password" class="setting-input"
                      placeholder="当前密码" autocomplete="current-password" />
                    <input v-model="pwdForm.new1" type="password" class="setting-input"
                      placeholder="新密码（至少 8 位）" autocomplete="new-password" />
                    <input v-model="pwdForm.new2" type="password" class="setting-input"
                      placeholder="确认新密码" autocomplete="new-password" />
                    <div class="setting-actions">
                      <button class="btn-primary" @click="changePassword" :disabled="pwdSaving">
                        <Icon :icon="pwdSaving ? 'mdi:loading' : 'mdi:lock-reset'" width="14"
                          :class="{ spin: pwdSaving }" />
                        {{ pwdSaving ? '修改中...' : '确认修改' }}
                      </button>
                      <span v-if="pwdMsg" class="form-msg" :class="pwdMsgType">{{ pwdMsg }}</span>
                    </div>
                  </div>
                </template>

                <!-- 偏好设置 -->
                <template v-if="settingsTab === 'preferences'">
                  <div class="grok-row clickable" @click="setTheme(currentTheme === 'dark' ? 'light' : 'dark')">
                    <div class="grok-row-info">
                      <p class="grok-row-title">外观主题</p>
                      <p class="grok-row-sub">{{ currentTheme === 'dark' ? '深色模式' : '浅色模式' }}</p>
                    </div>
                    <button class="btn-action">更改</button>
                  </div>

                  <div class="grok-row">
                    <div class="grok-row-info">
                      <p class="grok-row-title">默认联网搜索</p>
                      <p class="grok-row-sub">新建会话时自动开启 Web 搜索增强</p>
                    </div>
                    <label class="toggle-switch">
                      <input type="checkbox" v-model="webSearchDefault" @change="saveWebSearchPref" />
                      <span class="toggle-track"></span>
                    </label>
                  </div>

                  <div class="grok-row disabled">
                    <div class="grok-row-info">
                      <p class="grok-row-title">工单状态通知 <span class="coming-soon">即将推出</span></p>
                      <p class="grok-row-sub">审批工单状态更新时接收系统消息</p>
                    </div>
                    <label class="toggle-switch">
                      <input type="checkbox" disabled />
                      <span class="toggle-track"></span>
                    </label>
                  </div>

                  <div class="grok-row disabled">
                    <div class="grok-row-info">
                      <p class="grok-row-title">异常事件推送 <span class="coming-soon">即将推出</span></p>
                      <p class="grok-row-sub">检测到能耗异常时实时推送提醒</p>
                    </div>
                    <label class="toggle-switch">
                      <input type="checkbox" disabled />
                      <span class="toggle-track"></span>
                    </label>
                  </div>
                </template>

              </div>
            </template>

            <!-- ═══════════ 消息中心 ═══════════ -->
            <template v-if="activeSection === 'messages'">

              <!-- ── 胶囊切换 ── -->
              <div class="msg-capsule-wrap">
                <div class="msg-capsule">
                  <button
                    class="capsule-btn"
                    :class="{ active: msgTab === 'workorder' }"
                    @click="switchMsgTab('workorder')"
                  >
                    <Icon icon="mdi:clipboard-clock-outline" width="13" />
                    工单动态
                    <span v-if="notificationStore.unreadCount > 0" class="capsule-dot ok">{{ notificationStore.unreadCount }}</span>
                  </button>
                  <button
                    class="capsule-btn"
                    :class="{ active: msgTab === 'anomaly' }"
                    @click="switchMsgTab('anomaly')"
                  >
                    <Icon icon="mdi:bell-ring-outline" width="13" />
                    异常告警
                    <span v-if="anomalies.length > 0" class="capsule-dot">{{ anomalies.length > 99 ? '99+' : anomalies.length }}</span>
                  </button>
                  <button
                    class="capsule-btn"
                    :class="{ active: msgTab === 'warning' }"
                    @click="switchMsgTab('warning')"
                  >
                    <Icon icon="mdi:lightning-bolt-outline" width="13" />
                    预警通知
                    <span v-if="riskHighCount > 0" class="capsule-dot warn">{{ riskHighCount }}</span>
                  </button>
                </div>
              </div>

              <!-- ── 筛选栏 ── -->
              <div v-if="msgTab !== 'workorder'" class="msg-filter-bar" @click.self="closeDropdowns">
                <div class="filter-fields">
                  <!-- 建筑下拉 -->
                  <div class="filter-pill" :class="{ 'filter-pill--active': filterBuilding !== 'all', 'filter-pill--open': dropdownBuildingOpen }" @click.stop="dropdownBuildingOpen = !dropdownBuildingOpen; dropdownTimeOpen = false">
                    <Icon icon="mdi:office-building-outline" width="14" class="pill-icon" />
                    <div class="pill-inner">
                      <span class="pill-label">建筑</span>
                      <span class="pill-value">{{ BUILDING_OPTIONS.find(o => o.value === filterBuilding)?.label }}</span>
                    </div>
                    <Icon icon="mdi:chevron-down" width="14" class="pill-chevron" :class="{ 'pill-chevron--open': dropdownBuildingOpen }" />
                    <!-- 下拉列表 -->
                    <Transition name="dropdown">
                      <div v-if="dropdownBuildingOpen" class="custom-dropdown" @click.stop>
                        <div
                          v-for="opt in BUILDING_OPTIONS"
                          :key="opt.value"
                          class="dropdown-item"
                          :class="{ 'dropdown-item--selected': filterBuilding === opt.value }"
                          @click="selectBuilding(opt.value)"
                        >
                          <Icon v-if="filterBuilding === opt.value" icon="mdi:check" width="14" class="item-check" />
                          <span>{{ opt.label }}</span>
                        </div>
                      </div>
                    </Transition>
                  </div>

                  <!-- 时间范围下拉（预警通知 tab 仅显示 6h/12h） -->
                  <div class="filter-pill" :class="{ 'filter-pill--active': filterHours !== 0, 'filter-pill--open': dropdownTimeOpen }" @click.stop="dropdownTimeOpen = !dropdownTimeOpen; dropdownBuildingOpen = false">
                    <Icon icon="mdi:clock-outline" width="14" class="pill-icon" />
                    <div class="pill-inner">
                      <span class="pill-label">{{ msgTab === 'warning' ? '预测窗口' : '时间范围' }}</span>
                      <span class="pill-value">{{ currentTimeOptions.find(o => o.value === filterHours)?.label ?? (msgTab === 'warning' ? '6 小时' : '全部时间') }}</span>
                    </div>
                    <Icon icon="mdi:chevron-down" width="14" class="pill-chevron" :class="{ 'pill-chevron--open': dropdownTimeOpen }" />
                    <!-- 下拉列表 -->
                    <Transition name="dropdown">
                      <div v-if="dropdownTimeOpen" class="custom-dropdown" @click.stop>
                        <div
                          v-for="opt in currentTimeOptions"
                          :key="opt.value"
                          class="dropdown-item"
                          :class="{ 'dropdown-item--selected': filterHours === opt.value }"
                          @click="selectTime(opt.value)"
                        >
                          <Icon v-if="filterHours === opt.value" icon="mdi:check" width="14" class="item-check" />
                          <span>{{ opt.label }}</span>
                        </div>
                      </div>
                    </Transition>
                  </div>
                </div>

                <div class="filter-actions">
                  <template v-if="msgTab === 'warning'">
                    <!-- 预警通知专属：重新预测按钮 -->
                    <button
                      class="filter-btn filter-btn--forecast"
                      :disabled="forecastLoading"
                      @click="runForecast"
                    >
                      <Icon :icon="forecastLoading ? 'mdi:loading' : 'mdi:refresh'" width="14" :class="{ spin: forecastLoading }" />
                      {{ forecastLoading ? '预测中...' : '重新预测' }}
                    </button>
                  </template>
                  <template v-else>
                    <button v-if="hasActiveFilter" class="filter-btn filter-btn--reset" @click="resetFilters()">
                      <Icon icon="mdi:close" width="13" />
                      重置
                    </button>
                    <button class="filter-btn filter-btn--apply" :class="{ 'filter-btn--active': hasActiveFilter }">
                      <Icon icon="mdi:filter-outline" width="14" />
                      筛选
                    </button>
                  </template>
                </div>
              </div>

              <!-- ── Tab: 工单动态 ── -->
              <div v-if="msgTab === 'workorder'" class="msg-tab-content">
                <WorkorderNotificationPanel />
              </div>
              <div v-if="false && msgTab === 'workorder'" class="msg-tab-content">
                <div class="msg-block">
                  <p class="block-label">
                    <Icon icon="mdi:clipboard-clock-outline" width="13" />
                    工单动态
                    <span v-if="filteredWorkorderItems.length > 0" class="count-badge">{{ filteredWorkorderItems.length }}</span>
                  </p>
                  <div v-if="workorderLoading && workorderItems.length === 0" class="empty-state">
                    <Icon icon="mdi:loading" width="24" class="empty-icon spin" />
                    <p>工单动态加载中…</p>
                  </div>
                  <div v-else-if="filteredWorkorderItems.length === 0" class="empty-state ok">
                    <Icon icon="mdi:check-circle-outline" width="26" class="empty-icon" />
                    <p>{{ hasActiveFilter ? '当前筛选条件下暂无工单提醒' : '暂无待处理工单提醒' }}</p>
                  </div>
                  <div v-else class="msg-list">
                    <template v-if="workorderGroups.review.length">
                      <p class="block-label block-label-hint">待审批 / 待派工 / 工单大厅申请</p>
                      <div
                        v-for="item in workorderGroups.review"
                        :key="item.id"
                        class="msg-item clickable"
                        @click="gotoWorkOrder(item)"
                      >
                        <div class="msg-icon workorder">
                          <Icon icon="mdi:wrench-clock" width="15" />
                        </div>
                        <div class="msg-body">
                          <p class="msg-title">{{ item.title }}</p>
                          <p class="msg-sub">{{ item.subtitle }}</p>
                          <p class="msg-detail">{{ item.detail }}</p>
                          <div v-if="hasWorkorderQuickActions(item)" class="msg-actions" @click.stop>
                            <button
                              v-if="canNudgeWorkorderItem(item)"
                              class="msg-action-btn accent"
                              @click.stop="handleWorkorderQuickAction(item, 'nudge')"
                            >催办</button>
                            <button
                              v-if="canSuggestReassign(item)"
                              class="msg-action-btn warn"
                              @click.stop="handleWorkorderQuickAction(item, 'suggest_reassign')"
                            >改派建议</button>
                          </div>
                        </div>
                        <span class="msg-tag" :class="'tag-' + item.tone">{{ item.tag }}</span>
                        <Icon icon="mdi:chevron-right" width="14" class="msg-chevron" />
                      </div>
                    </template>

                    <template v-if="workorderGroups.execution.length">
                      <p class="block-label block-label-hint">执行提醒</p>
                      <div
                        v-for="item in workorderGroups.execution"
                        :key="item.id"
                        class="msg-item clickable"
                        @click="gotoWorkOrder(item)"
                      >
                        <div class="msg-icon workorder" :class="'icon-' + item.tone">
                          <Icon
                            :icon="item.category === 'waiting_support'
                              ? 'mdi:account-group-outline'
                              : item.category === 'overdue'
                                ? 'mdi:timer-alert-outline'
                                : item.dispatchStage === 'arrive'
                                  ? 'mdi:map-marker-path'
                                  : item.dispatchStage === 'accept'
                                    ? 'mdi:send-check-outline'
                                    : 'mdi:bell-ring-outline'"
                            width="15"
                          />
                        </div>
                        <div class="msg-body">
                          <p class="msg-title">{{ item.title }}</p>
                          <p class="msg-sub">{{ item.subtitle }}</p>
                          <p class="msg-detail">{{ item.detail }}</p>
                        </div>
                        <span class="msg-tag" :class="'tag-' + item.tone">{{ item.tag }}</span>
                        <Icon icon="mdi:chevron-right" width="14" class="msg-chevron" />
                      </div>
                    </template>

                    <template v-if="workorderGroups.closing.length">
                      <p class="block-label block-label-hint">待复核 / 待关闭</p>
                      <div
                        v-for="item in workorderGroups.closing"
                        :key="item.id"
                        class="msg-item clickable"
                        @click="gotoWorkOrder(item)"
                      >
                        <div class="msg-icon workorder icon-success">
                          <Icon icon="mdi:clipboard-check-outline" width="15" />
                        </div>
                        <div class="msg-body">
                          <p class="msg-title">{{ item.title }}</p>
                          <p class="msg-sub">{{ item.subtitle }}</p>
                          <p class="msg-detail">{{ item.detail }}</p>
                        </div>
                        <span class="msg-tag tag-success">{{ item.tag }}</span>
                        <Icon icon="mdi:chevron-right" width="14" class="msg-chevron" />
                      </div>
                    </template>
                  </div>
                </div>
              </div>

              <!-- ── Tab: 异常告警 ── -->
              <div v-if="msgTab === 'anomaly'" class="msg-tab-content">
                <div class="msg-block">
                  <p class="block-label">
                    <Icon icon="mdi:alert-circle-outline" width="13" />
                    已发生异常
                    <button class="refresh-btn" @click="loadAnomalies" :disabled="anomalyLoading" title="刷新">
                      <Icon :icon="anomalyLoading ? 'mdi:loading' : 'mdi:refresh'" width="12" :class="{ spin: anomalyLoading }" />
                    </button>
                  </p>
                  <div v-if="anomalyLoading && anomalies.length === 0" class="empty-state">
                    <Icon icon="mdi:loading" width="24" class="empty-icon spin" />
                    <p>加载中...</p>
                  </div>
                  <div v-else-if="anomalyError" class="empty-state error">
                    <Icon icon="mdi:alert" width="24" class="empty-icon" />
                    <p>{{ anomalyError }}</p>
                  </div>
                  <div v-else-if="filteredAnomalies.length === 0" class="empty-state ok">
                    <Icon icon="mdi:check-all" width="26" class="empty-icon" />
                    <p>{{ hasActiveFilter ? '当前筛选条件下无异常记录' : '近期无异常告警' }}</p>
                  </div>
                  <div v-else class="msg-list">
                    <div
                      v-for="(anom, idx) in filteredAnomalies"
                      :key="anom.timestamp + idx"
                      class="msg-item"
                      :class="'sev-' + deviationSeverity(anom.deviation_pct)"
                    >
                      <div class="msg-icon anom">
                        <Icon :icon="ruleIcon(anom.rule)" width="15" />
                      </div>
                      <div class="msg-body">
                        <p class="msg-title">{{ ruleLabel(anom.rule) }}</p>
                        <p class="msg-sub">
                          {{ buildingLabel(anom.building_type) }}
                          <template v-if="anom.deviation_pct != null">
                            · <span :class="'dev-' + deviationSeverity(anom.deviation_pct)">{{ anom.deviation_pct > 0 ? '+' : '' }}{{ anom.deviation_pct.toFixed(1) }}%</span>
                          </template>
                          · {{ formatDate(anom.timestamp) }}
                        </p>
                        <p v-if="anom.message" class="msg-detail">{{ anom.message }}</p>
                      </div>
                      <span class="msg-tag" :class="'tag-' + deviationSeverity(anom.deviation_pct)">
                        {{ { high: '严重', medium: '警告', low: '提示' }[deviationSeverity(anom.deviation_pct)] }}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- ── Tab: 预警通知 ── -->
              <div v-if="msgTab === 'warning'" class="msg-tab-content">
                <div class="msg-block">
                  <p class="block-label">
                    <Icon icon="mdi:lightning-bolt-outline" width="13" />
                    未来 {{ filterHours }} 小时预测预警
                    <button class="refresh-btn" @click="loadPredictions" :disabled="predictionLoading" title="刷新数据">
                      <Icon :icon="predictionLoading ? 'mdi:loading' : 'mdi:refresh'" width="12" :class="{ spin: predictionLoading }" />
                    </button>
                    <span v-if="forecastResult" class="forecast-result-hint">
                      <Icon icon="mdi:check-circle-outline" width="12" />
                      {{ forecastResult }}
                    </span>
                    <span v-else class="block-label-hint">仅展示最新一轮预测中的异常项 · {{ filterHours }}h 窗口</span>
                  </p>
                  <div v-if="predictionLoading && latestPredictions.length === 0" class="empty-state">
                    <Icon icon="mdi:loading" width="24" class="empty-icon spin" />
                    <p>正在加载预测预警...</p>
                  </div>
                  <div v-else-if="predictionError" class="empty-state error">
                    <Icon icon="mdi:alert" width="24" class="empty-icon" />
                    <p>{{ predictionError }}</p>
                  </div>
                  <div v-else-if="filteredPredictions.length === 0" class="empty-state ok">
                    <Icon icon="mdi:check-circle-outline" width="26" class="empty-icon" />
                    <p>{{ filterBuilding !== 'all' ? '该建筑在所选预测窗口内暂无异常预警' : `未来 ${filterHours} 小时暂无异常预警` }}</p>
                    <p v-if="predictionEmptyHint" class="msg-detail">{{ predictionEmptyHint }}</p>
                  </div>
                  <div v-else class="msg-list">
                    <div
                      v-for="prediction in filteredPredictions"
                      :key="prediction.id"
                      class="risk-card"
                      :class="'risk-' + prediction.risk_level"
                    >
                      <div class="risk-card-left">
                        <div class="risk-icon">
                          <Icon :icon="prediction.risk_level === 'critical' ? 'mdi:alert' : 'mdi:alert-circle-outline'" width="16" />
                        </div>
                        <div class="risk-info">
                          <div class="risk-header">
                            <span class="risk-name">{{ prediction.building_name }}</span>
                            <span class="risk-mode-badge">{{ predictionWindowLabel(prediction.horizon_h) }}</span>
                          </div>
                          <p class="risk-desc">{{ predictionSummary(prediction) }}</p>
                          <p class="risk-meta">
                            预测时刻 {{ formatDate(prediction.forecast_for_timestamp) }}
                            <template v-if="prediction.predicted_value != null || prediction.expected_value != null">
                              · 预测 {{ formatPredictionValue(prediction.predicted_value, prediction.metric_name) }}
                              <template v-if="prediction.expected_value != null">
                                / 基线 {{ formatPredictionValue(prediction.expected_value, prediction.metric_name) }}
                              </template>
                            </template>
                            <template v-if="prediction.deviation_pct != null">
                              · 偏差 <span :class="'dev-' + prediction.risk_level">{{ prediction.deviation_pct > 0 ? '+' : '' }}{{ prediction.deviation_pct }}%</span>
                            </template>
                          </p>
                        </div>
                      </div>
                      <span class="risk-level-badge" :class="'rlv-' + prediction.risk_level">
                        {{ predictionRiskLabel(prediction.risk_level) }}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

            </template>

            <!-- ═══════════ 帮助中心 ═══════════ -->
            <template v-if="activeSection === 'help'">
              <div class="faq-list">
                <div v-for="faq in FAQ_LIST" :key="faq.q" class="faq-item">
                  <button class="faq-question" @click="faq._open = !faq._open">
                    <Icon :icon="faq._open ? 'mdi:chevron-down' : 'mdi:chevron-right'" width="14" />
                    {{ faq.q }}
                  </button>
                  <div v-if="faq._open" class="faq-answer">{{ faq.a }}</div>
                </div>
              </div>
            </template>

            <!-- ═══════════ 反馈中心 ═══════════ -->
            <template v-if="activeSection === 'feedback'">
              <p class="body-desc">我们非常重视您的反馈，请描述您遇到的问题或功能建议。</p>
              <textarea
                v-model="feedbackText"
                class="feedback-textarea"
                placeholder="请描述您遇到的问题或功能建议..."
                rows="6"
              ></textarea>
              <div class="setting-actions">
                <button class="btn-primary" @click="submitFeedback" :disabled="feedbackSent || !feedbackText.trim()">
                  <Icon :icon="feedbackSent ? 'mdi:check' : 'mdi:send-outline'" width="14" />
                  {{ feedbackSent ? '感谢您的反馈！' : '提交反馈' }}
                </button>
              </div>
            </template>

          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, reactive, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import { useAuthStore } from '@/stores/authStore'
import { useChatStore } from '@/stores/chatStore'
import { useNotificationStore } from '@/stores/notificationCenterStore'
import WorkorderNotificationPanel from '@/components/notifications/WorkorderNotificationPanel.vue'
import { apiChangePassword, apiUpdateProfile } from '@/api/auth'
import { apiFetch } from '@/api/http'
import { ALL_BUILDING_FILTER_OPTIONS, getBuildingLabel } from '@/constants/buildings'
import {
  buildWorkorderNotificationItems,
  filterWorkorderNotificationItems,
  groupWorkorderNotificationItems,
  type WorkorderNotificationHallEntry,
  type WorkorderNotificationIncident,
  type WorkorderNotificationItem,
} from '@/utils/workorderNotification'

const props = defineProps<{
  visible: boolean
  initialSection?: string
}>()
const emit = defineEmits<{ close: [] }>()

const router = useRouter()
const authStore = useAuthStore()
const chatStore = useChatStore()
const notificationStore = useNotificationStore()

const user = computed(() => authStore.user)

// ── 当前显示的区块 ──────────────────────────────
const SECTION_TITLES: Record<string, string> = {
  settings: '设置',
  messages: '消息中心',
  help: '帮助中心',
  feedback: '反馈中心',
}

const activeSection = ref(props.initialSection ?? 'settings')

// 每次打开时同步 initialSection
watch(() => props.visible, (v) => {
  if (v && props.initialSection) {
    activeSection.value = props.initialSection
  }
})

// ── 设置子Tab ──────────────────────────────────
const SETTINGS_TABS = [
  { id: 'profile',     label: '个人资料', icon: 'mdi:account-outline' },
  { id: 'security',    label: '账号安全', icon: 'mdi:shield-lock-outline' },
  { id: 'preferences', label: '偏好设置', icon: 'mdi:tune-variant' },
]

const settingsTab = ref('profile')
const showPwdForm = ref(false)

// ── 角色元数据 ──────────────────────────────────
const ROLE_LABELS: Record<string, string> = {
  resident: '住户',
  ops: '运维人员',
  manager: '运维经理',
  admin: '系统管理员',
}

const avatarInitials = computed(() => {
  const name = user.value?.username ?? ''
  if (!name) return '?'
  return name.slice(0, 2).toUpperCase()
})

// ── 头像上传（本地 localStorage 存储）──────────────────────────
const avatarInputRef = ref<HTMLInputElement | null>(null)

const avatarUrl = ref<string>(
  localStorage.getItem(`avatar_${user.value?.id ?? 'guest'}`) ?? ''
)

// 用户 id 加载后同步头像
watch(user, (u) => {
  if (u?.id) {
    avatarUrl.value = localStorage.getItem(`avatar_${u.id}`) ?? ''
  }
}, { immediate: true })

function triggerAvatarUpload() {
  avatarInputRef.value?.click()
}

function onAvatarChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = async (ev) => {
    const dataUrl = ev.target?.result as string
    avatarUrl.value = dataUrl
    notificationStore.saveAvatar(user.value?.id ?? 'guest', dataUrl)
  }
  reader.readAsDataURL(file)
  if (avatarInputRef.value) avatarInputRef.value.value = ''
}

// ── 个人资料表单 ──────────────────────────────────
const editingField = ref('')

const profileForm = reactive({
  username: user.value?.username ?? '',
  email:    user.value?.email    ?? '',
  phone:    user.value?.phone    ?? '',
})

watch(user, (u) => {
  if (u) {
    profileForm.username = u.username ?? ''
    profileForm.email    = u.email    ?? ''
    profileForm.phone    = u.phone    ?? ''
  }
}, { immediate: true })

const profileSaving  = ref(false)
const profileMsg     = ref('')
const profileMsgType = ref<'ok' | 'err'>('ok')

function cancelEdit() {
  const u = user.value
  if (u) {
    profileForm.username = u.username ?? ''
    profileForm.email    = u.email    ?? ''
    profileForm.phone    = u.phone    ?? ''
  }
  editingField.value = ''
}

async function saveProfile() {
  if (!authStore.accessToken) return
  profileSaving.value = true
  profileMsg.value = ''
  try {
    const payload: { username?: string; email?: string; phone?: string } = {}
    if (editingField.value === 'username') payload.username = profileForm.username || undefined
    if (editingField.value === 'email')    payload.email    = profileForm.email    || undefined
    if (editingField.value === 'phone')    payload.phone    = profileForm.phone    || undefined

    const updated = await apiUpdateProfile(authStore.accessToken, payload)
    authStore.user = updated
    editingField.value = ''
    profileMsg.value = '保存成功'
    profileMsgType.value = 'ok'
  } catch (e: unknown) {
    profileMsg.value = (e as Error).message ?? '保存失败'
    profileMsgType.value = 'err'
  } finally {
    profileSaving.value = false
    setTimeout(() => { profileMsg.value = '' }, 3000)
  }
}

// ── 修改密码 ──────────────────────────────────
const pwdForm = reactive({ old: '', new1: '', new2: '' })
const pwdSaving = ref(false)
const pwdMsg = ref('')
const pwdMsgType = ref<'ok' | 'err'>('ok')

async function changePassword() {
  if (!pwdForm.old || !pwdForm.new1 || !pwdForm.new2) {
    pwdMsg.value = '请填写所有密码字段'
    pwdMsgType.value = 'err'
    return
  }
  if (pwdForm.new1 !== pwdForm.new2) {
    pwdMsg.value = '两次新密码不一致'
    pwdMsgType.value = 'err'
    return
  }
  if (!authStore.accessToken) return
  pwdSaving.value = true
  pwdMsg.value = ''
  try {
    await apiChangePassword(authStore.accessToken, pwdForm.old, pwdForm.new1)
    pwdMsg.value = '密码修改成功，请重新登录'
    pwdMsgType.value = 'ok'
    pwdForm.old = ''
    pwdForm.new1 = ''
    pwdForm.new2 = ''
    setTimeout(() => {
      authStore.logout()
      emit('close')
      router.push('/login')
    }, 2000)
  } catch (e: unknown) {
    pwdMsg.value = (e as Error).message ?? '修改失败'
    pwdMsgType.value = 'err'
  } finally {
    pwdSaving.value = false
  }
}

// ── 主题偏好 ──────────────────────────────────
const currentTheme = ref(localStorage.getItem('theme') ?? 'dark')

function setTheme(t: 'dark' | 'light') {
  currentTheme.value = t
  document.documentElement.dataset.theme = t
  localStorage.setItem('theme', t)
}

// ── Web Search 偏好 ──────────────────────────────
const WEB_SEARCH_PREF_KEY = 'chat_web_search_default'
const webSearchDefault = ref(localStorage.getItem(WEB_SEARCH_PREF_KEY) === 'true')

function saveWebSearchPref() {
  localStorage.setItem(WEB_SEARCH_PREF_KEY, String(webSearchDefault.value))
}

// ── 消息中心 ──────────────────────────────────
const msgTab = ref<'workorder' | 'anomaly' | 'warning'>('workorder')

// ── 筛选状态 ──────────────────────────────────
const filterBuilding = ref<string>('all')
const filterHours    = ref<number>(0)
const dropdownBuildingOpen = ref(false)
const dropdownTimeOpen     = ref(false)

function selectBuilding(val: string) {
  filterBuilding.value = val
  dropdownBuildingOpen.value = false
}
function selectTime(val: number) {
  filterHours.value = val
  dropdownTimeOpen.value = false
}
function closeDropdowns() {
  dropdownBuildingOpen.value = false
  dropdownTimeOpen.value = false
}

const BUILDING_OPTIONS = ALL_BUILDING_FILTER_OPTIONS
const TIME_OPTIONS = [
  { value: 0,    label: '全部时间' },
  { value: 24,   label: '近 24 小时' },
  { value: 168,  label: '近 7 天' },
  { value: 720,  label: '近 30 天' },
]

const WARNING_TIME_OPTIONS = [
  { value: 6,  label: '6 小时' },
  { value: 12, label: '12 小时' },
]

const currentTimeOptions = computed(() =>
  msgTab.value === 'warning' ? WARNING_TIME_OPTIONS : TIME_OPTIONS
)

const hasActiveFilter = computed(
  () => filterBuilding.value !== 'all' || filterHours.value !== 0
)

function resetFilters() {
  filterBuilding.value = 'all'
  filterHours.value    = 0
}

const filteredAnomalies = computed(() => {
  let list = anomalies.value
  if (filterBuilding.value !== 'all')
    list = list.filter(a => a.building_type === filterBuilding.value)
  if (filterHours.value > 0) {
    const cutoff = Date.now() - filterHours.value * 3600 * 1000
    list = list.filter(a => new Date(a.timestamp).getTime() >= cutoff)
  }
  return list
})

const filteredPredictions = computed(() =>
  filterBuilding.value === 'all'
    ? latestPredictions.value.filter(p => p.horizon_h === filterHours.value)
    : latestPredictions.value.filter(p => p.horizon_h === filterHours.value && p.building_type === filterBuilding.value)
)

const workorderIncidents = ref<WorkorderNotificationIncident[]>([])
const workorderHallEntries = ref<WorkorderNotificationHallEntry[]>([])
const workorderLoading = ref(false)
const workorderItems = computed(() =>
  buildWorkorderNotificationItems(workorderIncidents.value, workorderHallEntries.value)
)
const filteredWorkorderItems = computed(() =>
  filterWorkorderNotificationItems(workorderItems.value, {
    buildingId: filterBuilding.value,
    hours: filterHours.value,
  })
)
const workorderGroups = computed(() =>
  groupWorkorderNotificationItems(filteredWorkorderItems.value)
)

type WorkorderQuickAction = 'nudge' | 'suggest_reassign'

function switchMsgTab(tab: 'workorder' | 'anomaly' | 'warning') {
  msgTab.value = tab
  if (tab === 'workorder' && workorderItems.value.length === 0) loadWorkorderNotifications()
  if (tab === 'warning') {
    if (![6, 12].includes(filterHours.value)) filterHours.value = 6
    if (predictions.value.length === 0) loadPredictions()
  } else {
    if ([6, 12].includes(filterHours.value)) filterHours.value = 0
  }
}

async function loadWorkorderNotifications() {
  workorderLoading.value = true
  try {
    const [incidentData, hallData] = await Promise.all([
      apiFetch<{ incidents?: WorkorderNotificationIncident[] }>(
        '/api/incidents?workflow_status=pending_review,pending_dispatch,dispatched,completed,false_alarm,escalated&page=1&page_size=80',
      ),
      apiFetch<{ hall_entries?: WorkorderNotificationHallEntry[] }>(
        '/api/dispatch-hall?status=open&entry_type=support_request,takeover_candidate&include_applications=true&page=1&page_size=50',
      ),
    ])
    workorderIncidents.value = incidentData?.incidents ?? []
    workorderHallEntries.value = hallData?.hall_entries ?? []
  } catch {
    workorderIncidents.value = []
    workorderHallEntries.value = []
  } finally {
    workorderLoading.value = false
  }
}

function gotoWorkOrder(item: WorkorderNotificationItem) {
  emit('close')
  if (item.category === 'hall_application' || item.category === 'takeover_recommendation') {
    router.push({
      path: '/workorders',
      query: {
        active_tab: 'shared_hall',
        hall_entry_id: item.hallEntryId ?? undefined,
      },
    })
    return
  }
  router.push('/workorders')
}

function incidentForWorkorderItem(item: WorkorderNotificationItem) {
  if (item.category === 'hall_application' || item.category === 'takeover_recommendation') return null
  return workorderIncidents.value.find((incident) => incident.id === item.id) || null
}

function canNudgeWorkorderItem(item: WorkorderNotificationItem) {
  return ['pending_accept', 'warning', 'overdue', 'waiting_support'].includes(item.category)
    && Boolean(incidentForWorkorderItem(item)?.current_dispatch?.id)
}

function canSuggestReassign(item: WorkorderNotificationItem) {
  return (
    ['pending_accept', 'overdue', 'waiting_support', 'takeover_recommendation'].includes(item.category)
    && Boolean(item.ticketId || item.hallEntryId)
  )
}

function hasWorkorderQuickActions(item: WorkorderNotificationItem) {
  return canNudgeWorkorderItem(item) || canSuggestReassign(item)
}

function buildNudgeMessage(item: WorkorderNotificationItem) {
  if (item.category === 'pending_accept') return '工单已派发，请尽快接单确认并同步预计到场时间'
  if (item.category === 'waiting_support') return '当前工单处于待协同状态，请尽快同步协同进展'
  if (item.category === 'warning' || item.category === 'overdue') {
    if (item.dispatchStage === 'accept') return '当前工单接单节点临近或已经超时，请立即接单并反馈现场计划'
    if (item.dispatchStage === 'arrive') return '当前工单到场节点临近或已经超时，请尽快到场并同步现场进展'
    return '当前工单处理节点临近或已经超时，请尽快处理并回传最新进展'
  }
  return '请尽快跟进当前工单，并同步处理进度'
}

async function handleWorkorderQuickAction(item: WorkorderNotificationItem, action: WorkorderQuickAction) {
  if (action === 'suggest_reassign' && item.category === 'takeover_recommendation') {
    emit('close')
    await router.push({
      path: '/workorders',
      query: {
        active_tab: 'shared_hall',
        hall_entry_id: item.hallEntryId ?? undefined,
      },
    })
    return
  }

  const target = incidentForWorkorderItem(item)
  if (!target) return

  if (action === 'nudge') {
    if (!target.current_dispatch?.id) return
    try {
      await apiFetch(`/api/dispatch-tasks/${target.current_dispatch.id}/nudge`, {
        method: 'POST',
        body: JSON.stringify({ message: buildNudgeMessage(item) }),
      })
      await loadWorkorderNotifications()
      await notificationStore.refresh()
    } catch {
      // 静默失败，避免打断消息面板使用
    }
    return
  }

  emit('close')
  await router.push({
    path: '/workorders',
    query: {
      focus_ticket: item.ticketId ?? undefined,
      focus_action: 'reassign',
    },
  })
}

// ── 异常告警 ──────────────────────────────────
interface AnomalyItem {
  timestamp: string
  building_id?: string | number
  building_type?: string
  meter_device_id?: string
  rule?: string
  message?: string
  actual_value?: number
  expected_value?: number
  deviation_pct?: number
}

const RULE_LABELS: Record<string, string> = {
  electricity_overload:  '电耗超标',
  water_leak:            '水耗异常',
  hvac_overconsumption:  '空调能耗超标',
  supply_temp_deviation: '供水温度偏离',
  return_temp_deviation: '回水温度偏离',
  flag_water:            '水耗偏高',
  flag_electricity:      '总电耗偏高',
  flag_hvac_energy:      '空调能耗偏高',
  flag_supply_deviation: '供水温度偏离',
  flag_return_deviation: '回水温度偏离',
  A_low_efficiency:      '主机效能衰退',
  B_small_deltaT:        '水力失调（大流量小温差）',
  C_unexpected_on:       '非预期开机',
  other_hvac:            '其他空调故障',
}

const RULE_ICONS: Record<string, string> = {
  electricity_overload:  'mdi:lightning-bolt',
  water_leak:            'mdi:water-alert',
  hvac_overconsumption:  'mdi:air-conditioner',
  supply_temp_deviation: 'mdi:thermometer',
  return_temp_deviation: 'mdi:thermometer',
  flag_water:            'mdi:water-alert',
  flag_electricity:      'mdi:lightning-bolt',
  flag_hvac_energy:      'mdi:air-conditioner',
  flag_supply_deviation: 'mdi:thermometer',
  flag_return_deviation: 'mdi:thermometer',
  A_low_efficiency:      'mdi:gauge-low',
  B_small_deltaT:        'mdi:waves-arrow-right',
  C_unexpected_on:       'mdi:clock-alert-outline',
  other_hvac:            'mdi:air-conditioner',
}

function ruleLabel(rule?: string) {
  return RULE_LABELS[rule ?? ''] ?? rule ?? '未知异常'
}

function ruleIcon(rule?: string) {
  return RULE_ICONS[rule ?? ''] ?? 'mdi:alert-outline'
}

function deviationSeverity(pct?: number): 'high' | 'medium' | 'low' {
  const abs = Math.abs(pct ?? 0)
  if (abs >= 30) return 'high'
  if (abs >= 15) return 'medium'
  return 'low'
}

function buildingLabel(type?: string) {
  return getBuildingLabel(type, '—')
}

const anomalies = ref<AnomalyItem[]>([])
const anomalyLoading = ref(false)
const anomalyError = ref('')

async function loadAnomalies() {
  anomalyLoading.value = true
  anomalyError.value = ''
  try {
    const data = await apiFetch<{ anomalies: AnomalyItem[] }>('/api/anomalies/recent?hours=168')
    anomalies.value = data?.anomalies ?? []
    // 刷新后清除角标
    notificationStore.clearBadge()
  } catch (e: unknown) {
    anomalyError.value = (e as Error).message ?? '加载失败'
  } finally {
    anomalyLoading.value = false
  }
}

// ── 预警通知 ──────────────────────────────────
interface PredictionItem {
  id: string
  created_at: string | null
  as_of_timestamp: string | null
  forecast_for_timestamp: string | null
  horizon_h: number
  building_id: string
  building_name: string
  building_type?: string
  metric_name: string
  predicted_value: number | null
  expected_value: number | null
  deviation_pct: number | null
  risk_level: 'warning' | 'critical' | 'normal'
  rule_triggered: string | null
  model_name: string | null
  is_confirmed: boolean | null
}

interface PredictionListResponse {
  predictions?: PredictionItem[]
  total?: number
  module_status?: 'ok' | 'no_data'
  message?: string
}

const predictions = ref<PredictionItem[]>([])
const predictionLoading = ref(false)
const predictionError = ref('')
const predictionEmptyHint = ref('')
const latestPredictionBatchAt = computed(() => {
  const timestamps = predictions.value
    .map(item => item.as_of_timestamp || item.created_at)
    .filter((value): value is string => Boolean(value))
    .sort((a, b) => new Date(b).getTime() - new Date(a).getTime())
  return timestamps[0] ?? null
})
const latestPredictions = computed(() =>
  predictions.value.filter(item => (item.as_of_timestamp || item.created_at) === latestPredictionBatchAt.value)
)
const riskHighCount = computed(() =>
  latestPredictions.value.filter(item => item.risk_level === 'warning' || item.risk_level === 'critical').length
)

async function loadPredictions() {
  predictionLoading.value = true
  predictionError.value = ''
  predictionEmptyHint.value = ''
  try {
    const data = await apiFetch<PredictionListResponse>('/api/predictions/recent?hours=168')
    predictions.value = (data?.predictions ?? [])
      .filter(item => item.risk_level === 'warning' || item.risk_level === 'critical')
      .sort((a, b) => {
        const order = { critical: 0, warning: 1 }
        const levelDiff = order[a.risk_level as keyof typeof order] - order[b.risk_level as keyof typeof order]
        if (levelDiff !== 0) return levelDiff
        return Math.abs(b.deviation_pct ?? 0) - Math.abs(a.deviation_pct ?? 0)
      })
    if (predictions.value.length === 0 && data?.module_status === 'no_data') {
      predictionEmptyHint.value = '尚未生成预测预警，可点击“重新预测”获取最新结果。'
    } else if (predictions.value.length === 0 && data?.message) {
      predictionEmptyHint.value = data.message
    }
  } catch (e: unknown) {
    predictionError.value = (e as Error).message ?? '加载失败'
  } finally {
    predictionLoading.value = false
  }
}

const forecastLoading = ref(false)
const forecastResult  = ref<string>('')

async function runForecast() {
  forecastLoading.value = true
  forecastResult.value  = ''
  predictionError.value = ''
  predictionEmptyHint.value = ''
  try {
    const res = await apiFetch<{
      status: string
      succeeded: number
      failed: number
      total_buildings: number
      total_warnings: number
      per_building?: Record<string, { status?: string; error?: string }>
    }>(
      '/api/admin/run-forecast',
      { method: 'POST' },
    )
    const succeeded = res.succeeded ?? 0
    const failed = res.failed ?? 0
    const totalBuildings = res.total_buildings ?? 0
    const totalWarnings = res.total_warnings ?? 0
    const firstError = Object.values(res.per_building ?? {})
      .find(item => item?.status === 'error' && item?.error)
      ?.error

    if (succeeded === 0 && failed > 0) {
      predictionError.value = firstError
        ? `预测执行失败：${failed}/${totalBuildings} 栋楼未完成。${firstError}`
        : `预测执行失败：${failed}/${totalBuildings} 栋楼未完成，请检查预测模型和历史数据。`
      return
    }

    if (totalWarnings > 0) {
      forecastResult.value = failed > 0
        ? `预测完成：${succeeded}/${totalBuildings} 栋楼，发现 ${totalWarnings} 条预警，另有 ${failed} 栋未完成`
        : `预测完成：${succeeded}/${totalBuildings} 栋楼，发现 ${totalWarnings} 条预警`
    } else if (failed > 0) {
      forecastResult.value = `预测完成：${succeeded}/${totalBuildings} 栋楼，当前未发现异常预警，另有 ${failed} 栋未完成`
    } else {
      forecastResult.value = `预测完成：${succeeded}/${totalBuildings} 栋楼，当前未发现异常预警`
    }
    await loadPredictions()
  } catch (e: unknown) {
    predictionError.value = (e as Error).message ?? '预测失败'
  } finally {
    forecastLoading.value = false
    setTimeout(() => { forecastResult.value = '' }, 4000)
  }
}

// ── FAQ ──────────────────────────────────
interface FaqItem { q: string; a: string; _open: boolean }

const FAQ_LIST = reactive<FaqItem[]>([
  { q: '如何发起 AI 诊断工单？', a: '在右侧 AI 控制台向 AI 描述问题（如"3号楼空调能耗偏高"），AI 将自动分析并生成工单，您可在"工单管理"页面审批执行。', _open: false },
  { q: '如何上传数据进行分析？', a: '进入"数据中心"页面，点击"上传数据集"按钮，支持 CSV / Excel 格式。上传后可在 AI 对话中引用该数据集进行问答分析。', _open: false },
  { q: '主题颜色如何切换？', a: '在"设置 → 偏好设置"中切换"深色"或"浅色"主题，也可通过左侧导航栏底部的调色板图标快速切换。', _open: false },
  { q: '联网搜索有什么用？', a: '开启后，AI 在回答问题时会主动搜索互联网获取最新资料，适合查询行业规范、政策法规等外部知识。可在 AI 控制台底部单独切换。', _open: false },
  { q: '如何联系技术支持？', a: '请发送邮件至 support@yourcompany.com 或通过"反馈中心"提交问题，我们将在 1 个工作日内响应。', _open: false },
])

// ── 反馈 ──────────────────────────────────
const feedbackText = ref('')
const feedbackSent = ref(false)

function submitFeedback() {
  if (!feedbackText.value.trim()) return
  feedbackSent.value = true
  setTimeout(() => {
    feedbackText.value = ''
    feedbackSent.value = false
  }, 3000)
}

// ── 工具函数 ──────────────────────────────────
function formatDate(dateStr?: string | null): string {
  if (!dateStr) return '—'
  try {
    return new Date(dateStr).toLocaleDateString('zh-CN', {
      year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return dateStr
  }
}

function predictionWindowLabel(horizon: number): string {
  return `${horizon}h`
}

function predictionRiskLabel(level: PredictionItem['risk_level']): string {
  return level === 'critical' ? '高风险' : level === 'warning' ? '预警' : '正常'
}

function metricLabel(metricName: string): string {
  const labels: Record<string, string> = {
    electricity_kwh: '用电量',
    water_l: '水耗',
    hac_energy: '空调能耗',
    sim_supply_temp_c: '供水温度',
    sim_return_temp_c: '回水温度',
  }
  return labels[metricName] ?? metricName
}

function metricUnit(metricName: string): string {
  const units: Record<string, string> = {
    electricity_kwh: 'kWh',
    water_l: 'L',
    hac_energy: 'kWh',
    sim_supply_temp_c: '℃',
    sim_return_temp_c: '℃',
  }
  return units[metricName] ?? ''
}

function formatPredictionValue(value: number | null, metricName: string): string {
  if (value == null || Number.isNaN(value)) return '--'
  const unit = metricUnit(metricName)
  return `${value.toFixed(2)}${unit ? ` ${unit}` : ''}`
}

function predictionSummary(item: PredictionItem): string {
  const metric = RULE_LABELS[item.rule_triggered ?? ''] ?? metricLabel(item.metric_name)
  return item.risk_level === 'critical'
    ? `${metric} 预计显著异常`
    : `${metric} 预计偏离基线`
}

// ── 初始化 ──────────────────────────────────
onMounted(() => {
  loadWorkorderNotifications()
  loadAnomalies()
  loadPredictions()
  document.addEventListener('click', closeDropdowns)
})

onUnmounted(() => {
  document.removeEventListener('click', closeDropdowns)
})
</script>

<style scoped>
/* ── 遮罩层 ── */
.pm-overlay {
  position: fixed;
  inset: 0;
  z-index: 9000;
  background: rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ── 弹窗主体 ── */
.pm-dialog {
  width: 640px;
  max-width: 94vw;
  height: 520px;
  max-height: 94vh;
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 18px;
  box-shadow:
    0 4px 6px -1px rgba(0, 0, 0, 0.04),
    0 16px 40px -8px rgba(0, 0, 0, 0.12);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.pm-dialog.section-messages { width: 720px; height: 680px; }

:deep([data-theme="dark"]) .pm-dialog,
:root[data-theme="dark"] .pm-dialog {
  background: #1a2420;
  border-color: rgba(255, 255, 255, 0.06);
  box-shadow:
    0 4px 6px -1px rgba(0, 0, 0, 0.15),
    0 16px 40px -8px rgba(0, 0, 0, 0.4);
}

/* ── 顶部标题栏 ── */
.pm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px 16px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  flex-shrink: 0;
}

.pm-title {
  font-size: 18px;
  font-weight: 700;
  color: #111827;
  margin: 0;
  letter-spacing: -0.01em;
}

.pm-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: none;
  border: none;
  border-radius: 8px;
  color: #9ca3af;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}
.pm-close:hover {
  background: #f3f4f6;
  color: #374151;
}

/* ── 内容区 ── */
.pm-body {
  flex: 1;
  min-height: 0;
  padding: 20px 24px 24px;
  overflow-y: auto;
}
.pm-body.has-sidebar {
  display: flex;
  padding: 0;
  overflow: hidden;
}

/* ── 设置左侧Tab栏（Grok 风格） ── */
.settings-sidebar {
  width: 150px;
  flex-shrink: 0;
  padding: 16px 10px;
  border-right: 1px solid rgba(0, 0, 0, 0.05);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sidebar-tab {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: none;
  border: none;
  border-radius: 10px;
  color: #6b7280;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
  text-align: left;
  white-space: nowrap;
}
.sidebar-tab:hover {
  background: #f3f4f6;
  color: #374151;
}
.sidebar-tab.active {
  background: rgba(80, 200, 120, 0.08);
  color: #50c878;
  font-weight: 600;
}

/* ── 设置右侧内容 ── */
.settings-content {
  flex: 1;
  min-width: 0;
  padding: 20px 24px;
  overflow-y: auto;
}

/* ── Grok 风格行 ── */
.grok-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 0;
  border-bottom: 1px solid rgba(0, 0, 0, 0.04);
}
.grok-row:last-child { border-bottom: none; }
.grok-row.clickable {
  cursor: pointer;
  border-radius: 10px;
  padding: 16px 14px;
  margin: 0 -14px;
  border-bottom: none;
  transition: background 0.15s ease;
}
.grok-row.clickable:hover { background: #f9fafb; }
.grok-row.disabled { opacity: 0.4; pointer-events: none; }
.grok-row.user-row { padding-top: 4px; }

.grok-row-info { flex: 1; min-width: 0; }
.grok-row-title {
  font-size: 13.5px;
  font-weight: 500;
  color: #111827;
  margin: 0 0 2px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.grok-row-sub {
  font-size: 12px;
  color: #9ca3af;
  margin: 0;
}

/* 用户 ID（底部灰色小字） */
.grok-id {
  padding: 14px 0 0;
  font-size: 11px;
  font-family: 'JetBrains Mono', monospace;
  color: #d1d5db;
  margin: 0;
  text-align: center;
}

/* 展开编辑区 */
.grok-edit-area {
  padding: 0 0 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.grok-edit-area.pwd-form {
  gap: 10px;
}

/* 状态圆点 */
.status-dot {
  width: 10px; height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot.ok { background: #34d399; box-shadow: 0 0 6px rgba(52, 211, 153, 0.4); }
.status-dot.warn { background: #ef4444; box-shadow: 0 0 6px rgba(239, 68, 68, 0.3); }

/* ── 个人信息头部 ── */
.profile-header {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 4px 0 20px;
}

.profile-avatar-wrap {
  position: relative;
  width: 64px;
  height: 64px;
  border-radius: 50%;
  flex-shrink: 0;
  cursor: pointer;
  overflow: hidden;
}

.profile-avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 50%;
  display: block;
}

.profile-avatar-placeholder {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: linear-gradient(135deg, #6ee7a0, #50c878);
  display: flex;
  align-items: center;
  justify-content: center;
}

.avatar-initials {
  color: #fff;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 0.02em;
  user-select: none;
}

.avatar-overlay {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  color: #fff;
  font-size: 10px;
  font-weight: 500;
  opacity: 0;
  transition: opacity 0.18s ease;
}

.profile-avatar-wrap:hover .avatar-overlay {
  opacity: 1;
}

.avatar-file-input {
  display: none;
}

.profile-header-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.profile-name-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.profile-username {
  font-size: 17px;
  font-weight: 700;
  color: #111827;
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.profile-email-hint {
  font-size: 12px;
  color: #9ca3af;
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.profile-section-divider {
  height: 1px;
  background: rgba(0, 0, 0, 0.06);
  margin: 0 0 4px;
}

/* 旧版小头像兼容保留 */
.user-avatar {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  background: linear-gradient(135deg, #6ee7a0, #50c878);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.avatar-text {
  color: #fff;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

/* ── 角色标签 ── */
.role-badge {
  font-size: 11px; font-weight: 600; padding: 3px 10px;
  border-radius: 20px; letter-spacing: 0.03em; flex-shrink: 0;
}
.role-resident  { background: rgba(80, 200, 120, 0.1); color: #34d399; }
.role-ops       { background: rgba(56, 189, 248, 0.1); color: #38bdf8; }
.role-manager   { background: rgba(251, 191, 36, 0.1); color: #f59e0b; }
.role-admin     { background: rgba(239, 68, 68, 0.1);  color: #ef4444; }

/* ── 表单输入 ── */
.setting-input {
  width: 100%; padding: 8px 12px;
  background: #f9fafb; border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 10px; color: #111827; font-size: 13px;
  outline: none; transition: border-color 0.2s ease, box-shadow 0.2s ease;
  box-sizing: border-box;
}
.setting-input:focus {
  border-color: #50c878;
  box-shadow: 0 0 0 3px rgba(80, 200, 120, 0.1);
}

.setting-actions { display: flex; align-items: center; gap: 14px; padding-top: 14px; }

.row-btns {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.btn-primary.sm {
  padding: 5px 12px;
  font-size: 12px;
  height: auto;
  display: flex;
  align-items: center;
  gap: 4px;
}

.coming-soon {
  font-size: 10px; font-weight: 500;
  background: rgba(251, 191, 36, 0.1); color: #f59e0b;
  padding: 1px 8px; border-radius: 20px;
}

/* ── 按钮 ── */
.btn-primary {
  display: flex; align-items: center; gap: 7px; padding: 8px 20px;
  background: #50c878; color: #fff; border: none; border-radius: 10px;
  font-size: 13px; font-weight: 600; cursor: pointer;
  transition: background 0.15s ease, transform 0.1s ease;
}
.btn-primary:hover:not(:disabled) { background: #45b86c; }
.btn-primary:active:not(:disabled) { transform: scale(0.98); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-action {
  padding: 6px 16px; background: #f3f4f6;
  border: 1px solid rgba(0, 0, 0, 0.06); border-radius: 20px;
  color: #374151; font-size: 12px; font-weight: 500;
  cursor: pointer; transition: background 0.15s ease; flex-shrink: 0;
}
.btn-action:hover { background: #e5e7eb; }

.form-msg { font-size: 12px; font-weight: 500; }
.form-msg.ok  { color: #34d399; }
.form-msg.err { color: #ef4444; }

/* ── Toggle Switch ── */
.toggle-switch { position: relative; display: inline-block; width: 42px; height: 24px; flex-shrink: 0; cursor: pointer; }
.toggle-switch input { opacity: 0; width: 0; height: 0; }
.toggle-track {
  position: absolute; inset: 0; background: #d1d5db;
  border-radius: 24px; transition: background 0.25s ease;
}
.toggle-track::before {
  content: ''; position: absolute; width: 18px; height: 18px;
  left: 3px; bottom: 3px; background: #fff; border-radius: 50%;
  transition: transform 0.25s ease;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}
.toggle-switch input:checked + .toggle-track { background: #50c878; }
.toggle-switch input:checked + .toggle-track::before { transform: translateX(18px); }

/* ── 消息中心 ── */
.body-desc { font-size: 13px; color: #9ca3af; margin: 0 0 16px; line-height: 1.65; }

/* 胶囊切换 */
.msg-capsule-wrap {
  display: flex; justify-content: flex-start; margin-bottom: 18px;
}
.msg-capsule {
  display: inline-flex; align-items: center; gap: 2px;
  background: #f3f4f6; border-radius: 100px; padding: 3px;
}
.capsule-btn {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 6px 13px; border-radius: 100px; border: none;
  font-size: 12px; font-weight: 500; cursor: pointer;
  color: #6b7280; background: transparent;
  transition: background 0.18s ease, color 0.18s ease, box-shadow 0.18s ease;
  position: relative; white-space: nowrap;
}
.capsule-btn:hover { color: #374151; }
.capsule-btn.active {
  background: #fff; color: #111827; font-weight: 600;
  box-shadow: 0 1px 4px rgba(0,0,0,0.1), 0 0 0 1px rgba(0,0,0,0.04);
}
.capsule-dot {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 16px; height: 16px; border-radius: 20px; padding: 0 4px;
  font-size: 10px; font-weight: 700; line-height: 1;
  background: #ef4444; color: #fff;
}
.capsule-dot.warn { background: #f59e0b; }
.capsule-dot.ok   { background: #50c878; }

/* ── 筛选栏 ── */
.msg-filter-bar {
  display: flex; align-items: center; gap: 10px;
  margin-bottom: 16px;
}
.filter-fields {
  display: flex; flex: 1; gap: 8px;
}
.filter-pill {
  flex: 1; display: flex; align-items: center; gap: 9px;
  padding: 8px 12px;
  background: #fff;
  border: 1.5px solid #e5e7eb;
  border-radius: 10px;
  cursor: pointer;
  position: relative;
  user-select: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
}
.filter-pill:hover {
  border-color: #86efac;
  box-shadow: 0 0 0 3px rgba(80, 200, 120, 0.08);
}
.filter-pill--active {
  border-color: #50c878;
  background: #f0fdf4;
  box-shadow: 0 0 0 3px rgba(80, 200, 120, 0.1);
}
.filter-pill--open {
  border-color: #50c878;
  box-shadow: 0 0 0 3px rgba(80, 200, 120, 0.15);
}
.pill-icon {
  color: #9ca3af; flex-shrink: 0; transition: color 0.2s;
}
.filter-pill--active .pill-icon,
.filter-pill--open .pill-icon { color: #22c55e; }
.pill-inner {
  flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0;
}
.pill-label {
  font-size: 10px; font-weight: 600; color: #9ca3af;
  text-transform: uppercase; letter-spacing: 0.06em;
  line-height: 1; transition: color 0.2s;
}
.filter-pill--active .pill-label,
.filter-pill--open .pill-label { color: #16a34a; }
.pill-value {
  font-size: 13px; font-weight: 500; color: #111827; line-height: 1.2;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.filter-pill--active .pill-value { color: #15803d; }
.pill-chevron {
  color: #d1d5db; flex-shrink: 0;
  transition: color 0.2s, transform 0.2s ease;
}
.filter-pill--active .pill-chevron { color: #86efac; }
.pill-chevron--open { transform: rotate(180deg); color: #50c878 !important; }

/* 自定义下拉列表 */
.custom-dropdown {
  position: absolute;
  top: calc(100% + 6px); left: 0; right: 0;
  background: #fff;
  border: 1.5px solid #e5e7eb;
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.10), 0 2px 8px rgba(0, 0, 0, 0.06);
  overflow: hidden;
  z-index: 100;
  padding: 4px;
}
.dropdown-item {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 10px;
  border-radius: 7px;
  font-size: 13px; font-weight: 500; color: #374151;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}
.dropdown-item:hover {
  background: #f0fdf4; color: #15803d;
}
.dropdown-item--selected {
  background: #dcfce7; color: #16a34a; font-weight: 600;
}
.dropdown-item--selected:hover { background: #bbf7d0; }
.item-check { color: #22c55e; flex-shrink: 0; }

/* 下拉动画 */
.dropdown-enter-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.dropdown-leave-active { transition: opacity 0.1s ease, transform 0.1s ease; }
.dropdown-enter-from  { opacity: 0; transform: translateY(-6px) scale(0.97); }
.dropdown-leave-to    { opacity: 0; transform: translateY(-4px) scale(0.98); }
.filter-actions {
  display: flex; align-items: center; gap: 6px; flex-shrink: 0;
}
.filter-btn {
  display: flex; align-items: center; gap: 5px;
  padding: 8px 14px; border: none; border-radius: 9px;
  font-size: 13px; font-weight: 600; font-family: inherit;
  cursor: pointer; white-space: nowrap;
  transition: all 0.2s ease;
}
.filter-btn--apply {
  background: #50c878; color: #fff;
  box-shadow: 0 2px 8px rgba(80, 200, 120, 0.3);
}
.filter-btn--apply:hover { background: #3db86a; box-shadow: 0 3px 12px rgba(80, 200, 120, 0.4); transform: translateY(-1px); }
.filter-btn--apply:active { transform: translateY(0); box-shadow: 0 1px 4px rgba(80, 200, 120, 0.3); }
.filter-btn--apply.filter-btn--active { background: #22c55e; }
.filter-btn--reset {
  background: rgba(239, 68, 68, 0.07); color: #dc2626;
  border: 1.5px solid rgba(239, 68, 68, 0.15);
}
.filter-btn--reset:hover { background: rgba(239, 68, 68, 0.13); border-color: rgba(239, 68, 68, 0.3); }
.filter-btn--forecast {
  background: linear-gradient(135deg, #3b82f6, #6366f1);
  color: #fff; border: none;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.35);
}
.filter-btn--forecast:hover:not(:disabled) {
  background: linear-gradient(135deg, #2563eb, #4f46e5);
  box-shadow: 0 3px 12px rgba(99, 102, 241, 0.5);
  transform: translateY(-1px);
}
.filter-btn--forecast:active:not(:disabled) { transform: translateY(0); }
.filter-btn--forecast:disabled { opacity: 0.7; cursor: not-allowed; }

.msg-tab-content { animation: tabFadeIn 0.18s ease; }
@keyframes tabFadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}

.msg-block { margin-bottom: 20px; }
.msg-block:last-child { margin-bottom: 0; }
.msg-list > .block-label-hint:not(:first-child) {
  margin-top: 8px;
}
.block-label {
  display: flex; align-items: center; gap: 7px;
  font-size: 11px; font-weight: 600; color: #9ca3af;
  text-transform: uppercase; letter-spacing: 0.08em; margin: 0 0 10px;
}
.block-label-hint {
  font-size: 10px; font-weight: 400; color: #c4c9d4;
  text-transform: none; letter-spacing: 0;
}
.forecast-result-hint {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 10px; font-weight: 500; color: #22c55e;
  text-transform: none; letter-spacing: 0;
  animation: tabFadeIn 0.3s ease;
}
.count-badge {
  background: #50c878; color: #fff; font-size: 10px;
  min-width: 17px; height: 17px; border-radius: 20px; padding: 0 5px;
  display: flex; align-items: center; justify-content: center;
}
.refresh-btn {
  margin-left: auto; background: none; border: none; color: #9ca3af;
  cursor: pointer; padding: 2px 4px; border-radius: 6px; display: flex;
  align-items: center; transition: color 0.15s ease;
}
.refresh-btn:hover { color: #374151; }
.refresh-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.empty-state {
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  padding: 28px 16px; background: #f9fafb;
  border: 1px solid rgba(0, 0, 0, 0.04); border-radius: 12px;
  color: #9ca3af; font-size: 13px; text-align: center;
}
.empty-state.error { color: #ef4444; }
.empty-state.ok .empty-icon { color: #34d399; opacity: 0.8; }
.empty-icon { opacity: 0.35; }

.msg-list { display: flex; flex-direction: column; gap: 6px; }
.msg-item {
  display: flex; align-items: center; gap: 11px; padding: 11px 13px;
  background: #f9fafb; border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 12px;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.msg-item.clickable { cursor: pointer; }
.msg-item.clickable:hover {
  border-color: rgba(80, 200, 120, 0.25);
  background: rgba(80, 200, 120, 0.04);
}

.msg-icon {
  flex-shrink: 0; width: 32px; height: 32px; border-radius: 9px;
  display: flex; align-items: center; justify-content: center;
}
.msg-icon.workorder { background: rgba(80, 200, 120, 0.1); color: #50c878; }
.msg-icon.workorder.icon-warning { background: rgba(245, 158, 11, 0.12); color: #d97706; }
.msg-icon.workorder.icon-danger { background: rgba(239, 68, 68, 0.12); color: #dc2626; }
.msg-icon.workorder.icon-success { background: rgba(34, 197, 94, 0.12); color: #16a34a; }
.msg-icon.anom      { background: rgba(239, 68, 68, 0.08); color: #ef4444; }
.sev-high .msg-icon.anom   { background: rgba(239, 68, 68, 0.1); color: #ef4444; }
.sev-medium .msg-icon.anom { background: rgba(251, 191, 36, 0.08); color: #f59e0b; }
.sev-low .msg-icon.anom    { background: rgba(80, 200, 120, 0.08); color: #34d399; }

.msg-body { flex: 1; min-width: 0; }
.msg-title {
  font-size: 13px; font-weight: 600; color: #111827; margin: 0 0 3px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.msg-sub { font-size: 11px; color: #9ca3af; margin: 0; }
.msg-detail { font-size: 11px; color: #6b7280; margin: 3px 0 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.msg-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.msg-action-btn {
  border: none;
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 600;
  background: rgba(15, 23, 42, 0.05);
  color: #526071;
  cursor: pointer;
}
.msg-action-btn.accent { background: rgba(59, 130, 246, 0.12); color: #2563eb; }
.msg-action-btn.warn { background: rgba(245, 158, 11, 0.14); color: #d97706; }
.msg-chevron { color: #d1d5db; flex-shrink: 0; }
.msg-tag { font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 20px; flex-shrink: 0; }
.msg-tag.pending { background: rgba(80, 200, 120, 0.1); color: #16a34a; }
.msg-tag.tag-pending { background: rgba(80, 200, 120, 0.1); color: #16a34a; }
.msg-tag.tag-warning { background: rgba(245, 158, 11, 0.12); color: #d97706; }
.msg-tag.tag-danger { background: rgba(239, 68, 68, 0.12); color: #dc2626; }
.msg-tag.tag-success { background: rgba(34, 197, 94, 0.12); color: #16a34a; }
.msg-tag.tag-high   { background: rgba(239, 68, 68, 0.1); color: #dc2626; }
.msg-tag.tag-medium { background: rgba(251, 191, 36, 0.1); color: #d97706; }
.msg-tag.tag-low    { background: rgba(80, 200, 120, 0.1); color: #16a34a; }

/* 偏差高亮 */
.dev-high   { color: #dc2626; font-weight: 600; }
.dev-medium { color: #d97706; font-weight: 600; }
.dev-low    { color: #16a34a; font-weight: 600; }
.dev-critical { color: #dc2626; font-weight: 700; }
.dev-warning  { color: #d97706; font-weight: 700; }

/* ── 预警风险卡片 ── */
.risk-card {
  display: flex; align-items: center; gap: 10px; padding: 13px 14px;
  background: #f9fafb; border: 1px solid rgba(0, 0, 0, 0.05);
  border-radius: 13px; margin-bottom: 7px;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.risk-card:last-child { margin-bottom: 0; }
.risk-card.risk-critical { border-left: 3px solid #ef4444; background: rgba(239,68,68,0.02); }
.risk-card.risk-warning  { border-left: 3px solid #f59e0b; background: rgba(245,158,11,0.02); }

.risk-card-left { display: flex; align-items: flex-start; gap: 10px; flex: 1; min-width: 0; }
.risk-icon {
  flex-shrink: 0; width: 32px; height: 32px; border-radius: 9px;
  display: flex; align-items: center; justify-content: center; margin-top: 1px;
}
.risk-critical .risk-icon { background: rgba(239,68,68,0.1); color: #ef4444; }
.risk-warning .risk-icon  { background: rgba(245,158,11,0.1); color: #f59e0b; }

.risk-info { flex: 1; min-width: 0; }
.risk-header { display: flex; align-items: center; gap: 7px; margin-bottom: 3px; }
.risk-name { font-size: 13px; font-weight: 600; color: #111827; }
.risk-mode-badge {
  font-size: 10px; font-weight: 500; padding: 1px 7px; border-radius: 10px;
  background: rgba(59,108,244,0.1); color: #3b6cf4;
}
.risk-desc { font-size: 12px; color: #374151; margin: 0 0 3px; }
.risk-meta { font-size: 11px; color: #9ca3af; margin: 0; }

.risk-level-badge {
  flex-shrink: 0; font-size: 10px; font-weight: 700; padding: 3px 10px;
  border-radius: 20px; align-self: center;
}
.rlv-critical { background: rgba(239,68,68,0.1); color: #dc2626; }
.rlv-warning  { background: rgba(245,158,11,0.1); color: #d97706; }

/* ── FAQ ── */
.faq-list { display: flex; flex-direction: column; gap: 6px; }
.faq-question {
  display: flex; align-items: center; gap: 8px; width: 100%; padding: 12px 16px;
  background: #f9fafb; border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 10px; color: #374151; font-size: 13px;
  font-weight: 500; cursor: pointer; text-align: left;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.faq-question:hover { background: #f3f4f6; border-color: rgba(0, 0, 0, 0.08); }
.faq-answer {
  padding: 14px 18px; font-size: 13px; color: #6b7280; line-height: 1.7;
  background: #f9fafb; border: 1px solid rgba(0, 0, 0, 0.04);
  border-top: none; border-radius: 0 0 10px 10px; margin-top: -4px;
}

/* ── 反馈 ── */
.feedback-textarea {
  width: 100%; padding: 14px 16px;
  background: #f9fafb; border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 12px; color: #111827; font-size: 13px;
  resize: vertical; outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
  box-sizing: border-box; font-family: inherit; line-height: 1.65;
}
.feedback-textarea:focus {
  border-color: #50c878;
  box-shadow: 0 0 0 3px rgba(80, 200, 120, 0.1);
}

/* ── 深色模式适配 ── */
:root[data-theme="dark"] .pm-title { color: #f3f4f6; }
:root[data-theme="dark"] .pm-header { border-color: rgba(255,255,255,0.06); }
:root[data-theme="dark"] .pm-close { color: rgba(255,255,255,0.4); }
:root[data-theme="dark"] .pm-close:hover { background: rgba(255,255,255,0.06); color: #f3f4f6; }

/* 设置侧边栏 */
:root[data-theme="dark"] .settings-sidebar { border-color: rgba(255,255,255,0.06); }
:root[data-theme="dark"] .sidebar-tab { color: rgba(255,255,255,0.4); }
:root[data-theme="dark"] .sidebar-tab:hover { background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.8); }
:root[data-theme="dark"] .sidebar-tab.active { background: rgba(80,200,120,0.1); color: #6ee7a0; }

/* 个人信息头部深色 */
:root[data-theme="dark"] .profile-username { color: rgba(255,255,255,0.9); }
:root[data-theme="dark"] .profile-email-hint { color: rgba(255,255,255,0.35); }
:root[data-theme="dark"] .profile-section-divider { background: rgba(255,255,255,0.06); }

/* Grok 风格行 */
:root[data-theme="dark"] .grok-row { border-color: rgba(255,255,255,0.04); }
:root[data-theme="dark"] .grok-row.clickable:hover { background: rgba(255,255,255,0.04); }
:root[data-theme="dark"] .grok-row-title { color: rgba(255,255,255,0.88); }
:root[data-theme="dark"] .grok-row-sub { color: rgba(255,255,255,0.4); }
:root[data-theme="dark"] .grok-id { color: rgba(255,255,255,0.2); }

/* 表单 */
:root[data-theme="dark"] .setting-input { background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.08); color: #f3f4f6; }
:root[data-theme="dark"] .setting-input:focus { border-color: #50c878; box-shadow: 0 0 0 3px rgba(80,200,120,0.15); }
:root[data-theme="dark"] .btn-action { background: rgba(255,255,255,0.06); border-color: rgba(255,255,255,0.08); color: rgba(255,255,255,0.8); }
:root[data-theme="dark"] .btn-action:hover { background: rgba(255,255,255,0.1); }
:root[data-theme="dark"] .toggle-track { background: rgba(255,255,255,0.15); }
:root[data-theme="dark"] .body-desc { color: rgba(255,255,255,0.4); }

/* 消息中心 深色 */
:root[data-theme="dark"] .msg-filter-bar { background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.08); box-shadow: none; }
:root[data-theme="dark"] .filter-group:hover { background: rgba(255,255,255,0.04); }
:root[data-theme="dark"] .filter-label { color: rgba(255,255,255,0.3); }
:root[data-theme="dark"] .filter-select { color: rgba(255,255,255,0.85); }
:root[data-theme="dark"] .filter-chevron { color: rgba(255,255,255,0.2); }
:root[data-theme="dark"] .filter-divider { background: rgba(255,255,255,0.08); }
:root[data-theme="dark"] .filter-select option { background: #1a2420; color: #f3f4f6; }

:root[data-theme="dark"] .msg-capsule { background: rgba(255,255,255,0.06); }
:root[data-theme="dark"] .capsule-btn { color: rgba(255,255,255,0.4); }
:root[data-theme="dark"] .capsule-btn:hover { color: rgba(255,255,255,0.75); }
:root[data-theme="dark"] .capsule-btn.active { background: rgba(255,255,255,0.09); color: #f3f4f6; box-shadow: 0 1px 4px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.07); }

:root[data-theme="dark"] .empty-state { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.04); }
:root[data-theme="dark"] .msg-item { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.04); }
:root[data-theme="dark"] .msg-item.clickable:hover { background: rgba(80,200,120,0.06); border-color: rgba(80,200,120,0.15); }
:root[data-theme="dark"] .msg-title { color: #f3f4f6; }
:root[data-theme="dark"] .block-label { color: rgba(255,255,255,0.35); }
:root[data-theme="dark"] .block-label-hint { color: rgba(255,255,255,0.2); }
:root[data-theme="dark"] .msg-chevron { color: rgba(255,255,255,0.15); }

:root[data-theme="dark"] .risk-card { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.04); }
:root[data-theme="dark"] .risk-card.risk-critical { background: rgba(239,68,68,0.04); }
:root[data-theme="dark"] .risk-card.risk-warning  { background: rgba(245,158,11,0.04); }
:root[data-theme="dark"] .risk-name { color: rgba(255,255,255,0.9); }
:root[data-theme="dark"] .risk-desc { color: rgba(255,255,255,0.6); }
:root[data-theme="dark"] .risk-meta { color: rgba(255,255,255,0.3); }
:root[data-theme="dark"] .risk-mode-badge { background: rgba(59,108,244,0.16); color: #93c5fd; }

/* FAQ */
:root[data-theme="dark"] .faq-question { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.04); color: rgba(255,255,255,0.8); }
:root[data-theme="dark"] .faq-question:hover { background: rgba(255,255,255,0.06); border-color: rgba(255,255,255,0.08); }
:root[data-theme="dark"] .faq-answer { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.04); color: rgba(255,255,255,0.5); }

/* 反馈 */
:root[data-theme="dark"] .feedback-textarea { background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.06); color: #f3f4f6; }
:root[data-theme="dark"] .feedback-textarea:focus { border-color: #50c878; box-shadow: 0 0 0 3px rgba(80,200,120,0.15); }

/* ── 弹窗动画 ── */
.modal-fade-enter-active { transition: opacity 0.2s ease; }
.modal-fade-enter-active .pm-dialog { transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.2s ease; }
.modal-fade-leave-active { transition: opacity 0.15s ease; }
.modal-fade-leave-active .pm-dialog { transition: transform 0.15s ease, opacity 0.15s ease; }
.modal-fade-enter-from { opacity: 0; }
.modal-fade-enter-from .pm-dialog { transform: scale(0.96) translateY(8px); opacity: 0; }
.modal-fade-leave-to { opacity: 0; }
.modal-fade-leave-to .pm-dialog { transform: scale(0.96); opacity: 0; }

@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin 0.8s linear infinite; }

/* ── prefers-reduced-motion ── */
@media (prefers-reduced-motion: reduce) {
  .modal-fade-enter-active,
  .modal-fade-leave-active,
  .modal-fade-enter-active .pm-dialog,
  .modal-fade-leave-active .pm-dialog {
    transition: none;
  }
}
</style>
