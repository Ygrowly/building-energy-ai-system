<template>
  <div class="worker-profiles">
    <header class="page-header">
      <div>
        <h1><Icon icon="mdi:account-hard-hat" width="22" class="page-icon" /> 班组与人员画像</h1>
        <span class="subtitle">维护维修人员技能、班组、可派工状态与容量上限，为派工推荐和后续自动派工打地基。</span>
      </div>
      <button class="refresh-btn" @click="loadAll" :disabled="loading">
        <Icon :icon="loading ? 'mdi:loading' : 'mdi:refresh'" width="14" :class="{ spin: loading }" />
        {{ loading ? '刷新中...' : '刷新' }}
      </button>
    </header>

    <section class="summary-grid">
      <article class="summary-card">
        <span class="summary-label">维修人员</span>
        <strong>{{ summary.workers_total }}</strong>
        <small>已建账号</small>
      </article>
      <article class="summary-card active">
        <span class="summary-label">可派工</span>
        <strong>{{ summary.dispatch_enabled }}</strong>
        <small>参与候选推荐</small>
      </article>
      <article class="summary-card warning">
        <span class="summary-label">值班中</span>
        <strong>{{ summary.on_duty }}</strong>
        <small>当前优先分配</small>
      </article>
      <article class="summary-card danger">
        <span class="summary-label">容量满载</span>
        <strong>{{ summary.over_capacity }}</strong>
        <small>需调度关注</small>
      </article>
    </section>

    <div v-if="errorMsg" class="error-bar"><Icon icon="mdi:alert" width="14" /> {{ errorMsg }}</div>
    <div v-if="successMsg" class="success-bar"><Icon icon="mdi:check-circle" width="14" /> {{ successMsg }}</div>

    <section class="workbench">
      <aside class="roster-panel">
        <div class="filters">
          <div class="search-box">
            <Icon icon="mdi:magnify" width="15" />
            <input v-model="search" placeholder="搜索维修员 / 技能 / 班组" />
          </div>
          <select v-model="teamFilter">
            <option value="all">全部班组</option>
            <option value="none">未分配班组</option>
            <option v-for="team in options.teams" :key="team.id" :value="team.id">{{ team.name }}</option>
          </select>
          <select v-model="availabilityFilter">
            <option value="all">全部状态</option>
            <option value="enabled">可派工</option>
            <option value="disabled">停派</option>
            <option value="over_capacity">容量满载</option>
          </select>
        </div>

        <div v-if="loading" class="loading-state">正在加载人员画像...</div>
        <div v-else-if="filteredProfiles.length === 0" class="empty-state">没有匹配的维修人员</div>

        <button
          v-for="profile in filteredProfiles"
          :key="profile.user.id"
          class="worker-card"
          :class="{ active: selectedUserId === profile.user.id, disabled: !profile.dispatch_enabled }"
          @click="selectProfile(profile.user.id)"
        >
          <div class="worker-card-top">
            <div class="avatar">{{ profile.user.username.slice(0, 2).toUpperCase() }}</div>
            <div class="worker-main">
              <strong>{{ profile.user.username }}</strong>
              <span>{{ profile.team?.name || '未分配班组' }} · {{ profile.job_title || '维修员' }}</span>
            </div>
            <span class="status-dot" :class="profile.dispatch_enabled ? 'ok' : 'muted'"></span>
          </div>
          <div class="worker-card-meta">
            <span :class="['shift-chip', profile.shift_status]">{{ shiftLabel(profile.shift_status) }}</span>
            <span :class="['load-chip', capacityClass(profile)]">
              {{ profile.active_orders }}/{{ profile.max_active_orders }} 单
            </span>
            <span v-if="!profile.profile_exists" class="draft-chip">待补画像</span>
          </div>
          <div class="skill-line">
            {{ profile.skills.length ? profile.skills.map(item => item.name).filter(Boolean).slice(0, 3).join(' / ') : '未设置技能' }}
          </div>
        </button>
      </aside>

      <main class="editor-panel">
        <template v-if="selectedProfile">
          <div class="editor-header">
            <div>
              <p class="eyebrow">当前编辑</p>
              <h2>{{ selectedProfile.user.username }}</h2>
              <span>{{ selectedProfile.user.phone || '未设置手机号' }} · {{ selectedProfile.user.email || '未设置邮箱' }}</span>
            </div>
            <span :class="['capacity-badge', capacityClass(selectedProfile)]">
              当前负载 {{ selectedProfile.active_orders }}/{{ selectedProfile.max_active_orders }}
            </span>
          </div>

          <div class="form-grid">
            <label class="field">
              <span>班组</span>
              <select v-model="editForm.team_id">
                <option value="">未分配</option>
                <option v-for="team in options.teams" :key="team.id" :value="team.id">{{ team.name }}</option>
              </select>
            </label>
            <label class="field">
              <span>岗位</span>
              <input v-model="editForm.job_title" placeholder="例如：暖通维修员" />
            </label>
            <label class="field">
              <span>值班状态</span>
              <select v-model="editForm.shift_status">
                <option v-for="item in options.shift_statuses" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
            </label>
            <label class="field">
              <span>负载上限</span>
              <input v-model.number="editForm.max_active_orders" type="number" min="1" max="20" />
            </label>
          </div>

          <div class="switch-row">
            <label class="switch-card" :class="{ checked: editForm.dispatch_enabled }">
              <input v-model="editForm.dispatch_enabled" type="checkbox" />
              <span>允许参与派工推荐</span>
              <small>关闭后不会作为候选人优先推荐</small>
            </label>
            <label class="switch-card" :class="{ checked: editForm.accepts_emergency }">
              <input v-model="editForm.accepts_emergency" type="checkbox" />
              <span>可处理高优先级工单</span>
              <small>高优先级异常会获得额外匹配分</small>
            </label>
          </div>

          <section class="editor-section">
            <div class="section-title">
              <h3>技能标签</h3>
              <span>{{ editForm.skills.length }} 项已选</span>
            </div>
            <div class="skill-grid">
              <label
                v-for="skill in options.skills"
                :key="skill.id"
                class="skill-option"
                :class="{ checked: isSkillSelected(skill.id), primary: isPrimarySkill(skill.id) }"
              >
                <input type="checkbox" :checked="isSkillSelected(skill.id)" @change="onSkillToggle(skill.id, $event)" />
                <span class="skill-name">{{ skill.name }}</span>
                <small>{{ skill.category || skill.code }}</small>
                <select
                  :disabled="!isSkillSelected(skill.id)"
                  :value="skillDraft(skill.id)?.proficiency ?? 3"
                  @change="onSkillProficiencyChange(skill.id, $event)"
                >
                  <option v-for="level in [1,2,3,4,5]" :key="level" :value="level">{{ level }}级</option>
                </select>
                <button
                  type="button"
                  :disabled="!isSkillSelected(skill.id)"
                  class="primary-btn"
                  @click.prevent="markPrimarySkill(skill.id)"
                >
                  {{ isPrimarySkill(skill.id) ? '主技能' : '设主' }}
                </button>
              </label>
            </div>
          </section>

          <section class="editor-section">
            <div class="section-title">
              <h3>负责楼宇</h3>
              <span>{{ editForm.service_buildings.length }} 栋</span>
            </div>
            <div class="building-grid">
              <label v-for="building in options.buildings" :key="building.building_id" class="building-option">
                <input v-model="editForm.service_buildings" type="checkbox" :value="building.building_id" />
                <span>{{ buildingLabel(building.building_id) }}</span>
                <small>{{ building.primary_space_usage || '—' }}</small>
              </label>
            </div>
          </section>

          <label class="field notes-field">
            <span>调度备注</span>
            <textarea v-model="editForm.notes" rows="3" placeholder="例如：优先处理楼控联动问题，夜间不建议派远端楼宇"></textarea>
          </label>

          <div class="editor-actions">
            <button class="save-btn" @click="saveProfile" :disabled="saving">
              <Icon :icon="saving ? 'mdi:loading' : 'mdi:content-save-outline'" width="15" :class="{ spin: saving }" />
              {{ saving ? '保存中...' : '保存画像' }}
            </button>
          </div>
        </template>

        <div v-else class="empty-editor">
          <Icon icon="mdi:account-search-outline" width="44" />
          <p>请选择一个维修人员开始维护画像</p>
        </div>
      </main>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Icon } from '@iconify/vue'
import { getBuildingLabel } from '@/constants/buildings'
import {
  getWorkerProfileOptions,
  listWorkerProfiles,
  updateWorkerProfile,
  type WorkerBuildingOption,
  type WorkerProfileItem,
  type WorkerProfileOptionsResponse,
  type WorkerProfileSkill,
} from '@/api/workerProfiles'

const loading = ref(false)
const saving = ref(false)
const errorMsg = ref('')
const successMsg = ref('')
const search = ref('')
const teamFilter = ref('all')
const availabilityFilter = ref('all')
const selectedUserId = ref('')

const profiles = ref<WorkerProfileItem[]>([])
const summary = reactive({ workers_total: 0, dispatch_enabled: 0, on_duty: 0, over_capacity: 0 })
const options = reactive<WorkerProfileOptionsResponse>({
  teams: [],
  skills: [],
  buildings: [],
  shift_statuses: [
    { value: 'on_duty', label: '值班' },
    { value: 'standby', label: '备勤' },
    { value: 'busy', label: '忙碌' },
    { value: 'off_duty', label: '离岗' },
  ],
})

const editForm = reactive({
  team_id: '',
  job_title: '',
  shift_status: 'on_duty',
  dispatch_enabled: true,
  max_active_orders: 4,
  accepts_emergency: true,
  service_buildings: [] as string[],
  notes: '',
  skills: [] as Array<{ skill_id: string; proficiency: number; is_primary: boolean }>,
})

const selectedProfile = computed(() => profiles.value.find(item => item.user.id === selectedUserId.value) ?? null)

const filteredProfiles = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return profiles.value.filter((profile) => {
    if (teamFilter.value === 'none' && profile.team_id) return false
    if (teamFilter.value !== 'all' && teamFilter.value !== 'none' && profile.team_id !== teamFilter.value) return false
    if (availabilityFilter.value === 'enabled' && !profile.dispatch_enabled) return false
    if (availabilityFilter.value === 'disabled' && profile.dispatch_enabled) return false
    if (availabilityFilter.value === 'over_capacity' && profile.active_orders < profile.max_active_orders) return false
    if (!keyword) return true
    const haystack = [
      profile.user.username,
      profile.team?.name,
      profile.job_title,
      ...profile.skills.map(item => item.name || item.code || ''),
    ].join(' ').toLowerCase()
    return haystack.includes(keyword)
  })
})

function fillForm(profile: WorkerProfileItem | null) {
  if (!profile) return
  editForm.team_id = profile.team_id || ''
  editForm.job_title = profile.job_title || ''
  editForm.shift_status = profile.shift_status || 'on_duty'
  editForm.dispatch_enabled = profile.dispatch_enabled
  editForm.max_active_orders = profile.max_active_orders || 4
  editForm.accepts_emergency = profile.accepts_emergency
  editForm.service_buildings = [...profile.service_buildings]
  editForm.notes = profile.notes || ''
  editForm.skills = profile.skills.map(item => ({
    skill_id: item.skill_id,
    proficiency: item.proficiency,
    is_primary: item.is_primary,
  }))
}

function selectProfile(userId: string) {
  selectedUserId.value = userId
}

function shiftLabel(value: string) {
  return options.shift_statuses.find(item => item.value === value)?.label || value
}

function capacityClass(profile: WorkerProfileItem) {
  if (!profile.dispatch_enabled) return 'muted'
  if (profile.active_orders >= profile.max_active_orders) return 'danger'
  if (profile.active_orders >= Math.max(1, Math.floor(profile.max_active_orders * 0.75))) return 'warning'
  return 'ok'
}

function buildingLabel(buildingId: string) {
  return getBuildingLabel(buildingId, buildingId)
}

function skillDraft(skillId: string) {
  return editForm.skills.find(item => item.skill_id === skillId)
}

function isSkillSelected(skillId: string) {
  return Boolean(skillDraft(skillId))
}

function isPrimarySkill(skillId: string) {
  return Boolean(skillDraft(skillId)?.is_primary)
}

function onSkillToggle(skillId: string, event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  if (checked) {
    if (!isSkillSelected(skillId)) {
      editForm.skills.push({ skill_id: skillId, proficiency: 3, is_primary: editForm.skills.length === 0 })
    }
    return
  }
  editForm.skills = editForm.skills.filter(item => item.skill_id !== skillId)
  if (editForm.skills.length && !editForm.skills.some(item => item.is_primary)) {
    editForm.skills[0].is_primary = true
  }
}

function onSkillProficiencyChange(skillId: string, event: Event) {
  const draft = skillDraft(skillId)
  if (!draft) return
  draft.proficiency = Number((event.target as HTMLSelectElement).value || 3)
}

function markPrimarySkill(skillId: string) {
  if (!isSkillSelected(skillId)) return
  editForm.skills.forEach((item) => {
    item.is_primary = item.skill_id === skillId
  })
}

function applyProfileResult(profile: WorkerProfileItem) {
  const index = profiles.value.findIndex(item => item.user.id === profile.user.id)
  if (index >= 0) profiles.value[index] = profile
}

async function loadAll() {
  loading.value = true
  errorMsg.value = ''
  try {
    const [optionsRes, profilesRes] = await Promise.all([
      getWorkerProfileOptions(),
      listWorkerProfiles(),
    ])
    options.teams = optionsRes.teams
    options.skills = optionsRes.skills
    options.buildings = optionsRes.buildings
    options.shift_statuses = optionsRes.shift_statuses.length ? optionsRes.shift_statuses : options.shift_statuses
    profiles.value = profilesRes.profiles
    Object.assign(summary, profilesRes.summary)
    if (!selectedUserId.value && profiles.value.length) selectedUserId.value = profiles.value[0].user.id
    if (selectedUserId.value && !profiles.value.some(item => item.user.id === selectedUserId.value)) {
      selectedUserId.value = profiles.value[0]?.user.id || ''
    }
  } catch (error) {
    errorMsg.value = error instanceof Error ? error.message : '加载人员画像失败'
  } finally {
    loading.value = false
  }
}

async function saveProfile() {
  if (!selectedProfile.value) return
  saving.value = true
  errorMsg.value = ''
  successMsg.value = ''
  try {
    const updated = await updateWorkerProfile(selectedProfile.value.user.id, {
      team_id: editForm.team_id || null,
      job_title: editForm.job_title || null,
      shift_status: editForm.shift_status,
      dispatch_enabled: editForm.dispatch_enabled,
      max_active_orders: Number(editForm.max_active_orders) || 4,
      accepts_emergency: editForm.accepts_emergency,
      service_buildings: editForm.service_buildings,
      notes: editForm.notes || null,
      skills: editForm.skills,
    })
    applyProfileResult(updated)
    fillForm(updated)
    successMsg.value = '人员画像已保存，派工推荐会使用新的画像信息。'
    window.setTimeout(() => { successMsg.value = '' }, 2500)
  } catch (error) {
    errorMsg.value = error instanceof Error ? error.message : '保存失败'
  } finally {
    saving.value = false
  }
}

watch(selectedProfile, fillForm, { immediate: true })

onMounted(loadAll)
</script>

<style scoped>
.worker-profiles { padding: 24px; color: var(--text-primary); }
.page-header {
  margin-bottom: 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 16px 18px;
  border: 1px solid rgba(20, 184, 166, 0.24);
  border-radius: 20px;
  background:
    radial-gradient(circle at 8% 0%, rgba(20, 184, 166, 0.16), transparent 32%),
    linear-gradient(135deg, rgba(240, 253, 244, 0.82), rgba(255, 251, 235, 0.76)),
    var(--bg-panel);
  box-shadow: 0 14px 32px rgba(15, 23, 42, 0.07);
}
.page-header h1 { margin: 0 0 4px; display: flex; align-items: center; gap: 8px; font-size: 22px; }
.subtitle { color: var(--text-secondary); font-size: 13px; }
.refresh-btn, .save-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 9px 14px;
  color: var(--text-secondary);
  background: rgba(255, 255, 255, 0.74);
  cursor: pointer;
}
.save-btn {
  border-color: rgba(5, 150, 105, 0.28);
  color: #065f46;
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.18), rgba(250, 204, 21, 0.18));
  font-weight: 700;
}
.summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.summary-card {
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--bg-panel);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.summary-card strong { font-size: 26px; }
.summary-card small, .summary-label { color: var(--text-muted); font-size: 12px; }
.summary-card.active { border-color: rgba(16, 185, 129, 0.24); }
.summary-card.warning { border-color: rgba(245, 158, 11, 0.26); }
.summary-card.danger { border-color: rgba(248, 113, 113, 0.24); }
.error-bar, .success-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  border-radius: 12px;
  padding: 10px 14px;
  margin-bottom: 12px;
  font-size: 13px;
}
.error-bar { color: var(--danger); border: 1px solid rgba(248, 113, 113, 0.24); background: rgba(248, 113, 113, 0.08); }
.success-bar { color: #047857; border: 1px solid rgba(16, 185, 129, 0.24); background: rgba(16, 185, 129, 0.08); }
.workbench { display: grid; grid-template-columns: 360px minmax(0, 1fr); gap: 16px; align-items: start; }
.roster-panel, .editor-panel {
  border: 1px solid var(--border);
  border-radius: 20px;
  background: var(--bg-panel);
  box-shadow: 0 10px 26px rgba(15, 23, 42, 0.05);
}
.roster-panel { padding: 14px; display: flex; flex-direction: column; gap: 10px; max-height: calc(100vh - 230px); overflow: auto; }
.filters { display: grid; gap: 8px; }
.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 0 10px;
  background: rgba(255,255,255,0.72);
}
.search-box input, .filters select, .field input, .field select, .field textarea, .skill-option select {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-panel);
  color: var(--text-primary);
  padding: 9px 10px;
  outline: none;
}
.search-box input { border: none; background: transparent; }
.worker-card {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: rgba(255,255,255,0.66);
  padding: 12px;
  text-align: left;
  cursor: pointer;
  transition: all 0.18s ease;
}
.worker-card:hover, .worker-card.active { border-color: rgba(16, 185, 129, 0.34); box-shadow: 0 10px 22px rgba(16, 185, 129, 0.09); transform: translateY(-1px); }
.worker-card.disabled { opacity: 0.7; }
.worker-card-top { display: flex; align-items: center; gap: 10px; }
.avatar {
  width: 38px;
  height: 38px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, rgba(16,185,129,0.22), rgba(245,158,11,0.2));
  color: #065f46;
  font-weight: 800;
}
.worker-main { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 3px; }
.worker-main strong { font-size: 14px; }
.worker-main span, .skill-line { color: var(--text-muted); font-size: 12px; }
.status-dot { width: 9px; height: 9px; border-radius: 50%; background: #94a3b8; }
.status-dot.ok { background: #10b981; box-shadow: 0 0 0 4px rgba(16,185,129,0.12); }
.worker-card-meta { display: flex; gap: 6px; flex-wrap: wrap; margin: 10px 0 8px; }
.shift-chip, .load-chip, .draft-chip, .capacity-badge {
  border-radius: 999px;
  padding: 3px 8px;
  font-size: 11px;
  border: 1px solid var(--border);
  color: var(--text-secondary);
}
.shift-chip.on_duty, .load-chip.ok, .capacity-badge.ok { color: #047857; border-color: rgba(16,185,129,0.24); background: rgba(16,185,129,0.08); }
.shift-chip.busy, .load-chip.warning, .capacity-badge.warning { color: #b45309; border-color: rgba(245,158,11,0.28); background: rgba(245,158,11,0.1); }
.shift-chip.off_duty, .load-chip.danger, .capacity-badge.danger { color: #b91c1c; border-color: rgba(248,113,113,0.3); background: rgba(248,113,113,0.1); }
.shift-chip.standby { color: #0369a1; border-color: rgba(14,165,233,0.24); background: rgba(14,165,233,0.08); }
.draft-chip, .load-chip.muted, .capacity-badge.muted { background: rgba(148,163,184,0.12); }
.editor-panel { padding: 18px; min-height: 560px; }
.editor-header { display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--border); padding-bottom: 14px; margin-bottom: 16px; }
.editor-header h2 { margin: 2px 0 4px; }
.editor-header span, .eyebrow { color: var(--text-muted); font-size: 12px; }
.eyebrow { text-transform: uppercase; letter-spacing: 0.12em; margin: 0; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.field { display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: var(--text-secondary); }
.switch-row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 14px 0; }
.switch-card {
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 12px;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 3px 10px;
  cursor: pointer;
  background: rgba(255,255,255,0.58);
}
.switch-card.checked { border-color: rgba(16,185,129,0.28); background: rgba(16,185,129,0.08); }
.switch-card span { font-weight: 700; }
.switch-card small { grid-column: 2; color: var(--text-muted); }
.editor-section { margin-top: 16px; }
.section-title { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.section-title h3 { margin: 0; font-size: 15px; }
.section-title span { color: var(--text-muted); font-size: 12px; }
.skill-grid, .building-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 10px; }
.skill-option, .building-option {
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 10px;
  background: rgba(255,255,255,0.56);
  display: grid;
  gap: 6px;
}
.skill-option.checked, .building-option:has(input:checked) { border-color: rgba(16,185,129,0.32); background: rgba(16,185,129,0.08); }
.skill-option.primary { box-shadow: inset 3px 0 0 rgba(245,158,11,0.7); }
.skill-name { font-weight: 700; }
.skill-option small, .building-option small { color: var(--text-muted); }
.primary-btn {
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 5px 8px;
  background: rgba(255,255,255,0.7);
  color: var(--text-secondary);
  cursor: pointer;
}
.primary-btn:not(:disabled) { color: #065f46; }
.notes-field { margin-top: 16px; }
.editor-actions { display: flex; justify-content: flex-end; margin-top: 16px; }
.empty-state, .loading-state, .empty-editor {
  display: grid;
  place-items: center;
  gap: 8px;
  color: var(--text-muted);
  padding: 36px 12px;
}
.empty-editor { min-height: 440px; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 1180px) {
  .workbench { grid-template-columns: 1fr; }
  .roster-panel { max-height: none; }
}

@media (max-width: 760px) {
  .summary-grid, .form-grid, .switch-row { grid-template-columns: 1fr; }
  .page-header { align-items: flex-start; flex-direction: column; }
}
</style>
