/** Hermes REST（会话列表/历史）— 后端 SessionDB，非 UI 组件。 */

import { api } from "@hermes/lib/api";
import type { SessionInfo, SessionMessage } from "@hermes/lib/api";

export type { SessionInfo, SessionMessage };

export async function listHermesSessions(limit = 40, offset = 0) {
  return api.getSessions(limit, offset);
}

export async function loadHermesSessionMessages(sessionId: string) {
  return api.getSessionMessages(sessionId);
}

export async function deleteHermesSession(sessionId: string) {
  return api.deleteSession(sessionId);
}
