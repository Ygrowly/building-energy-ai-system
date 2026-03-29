/** 后端角色枚举（严格对齐 User.role） */
export type UserRole = 'resident' | 'ops' | 'manager' | 'admin'

/** 允许进入运维端的角色 */
export const OPERATOR_ROLES: UserRole[] = ['admin', 'manager']

/** 允许进入维修端的角色 */
export const WORKER_ROLES: UserRole[] = ['ops']

/** 允许使用手机端的全部角色 */
export const ALLOWED_ROLES: UserRole[] = [...OPERATOR_ROLES, ...WORKER_ROLES]

/** 角色中文映射 */
export const ROLE_LABEL: Record<UserRole, string> = {
  admin: '系统管理员',
  manager: '运维经理',
  ops: '维修人员',
  resident: '普通用户',
}

export function isOperatorRole(role: string): boolean {
  return OPERATOR_ROLES.includes(role as UserRole)
}

export function isWorkerRole(role: string): boolean {
  return WORKER_ROLES.includes(role as UserRole)
}
