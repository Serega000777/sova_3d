"use client";

import type {
  ModelComment,
  PhysicalAiClient,
  WorkspaceMember,
} from "@physical-ai/contracts";
import { ApiError } from "@physical-ai/contracts";
import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";

type Point = [number, number, number];

type Props = {
  client: PhysicalAiClient | null;
  versionId: string | null;
  workspaceId: string;
  canEdit: boolean;
  language: "ru" | "en";
  pendingPoint: Point | null;
  onPickPoint: () => void;
  onClearPoint: () => void;
  onCommentsChange: (comments: ModelComment[]) => void;
};

function mentionLabel(member: WorkspaceMember): string {
  return member.display_name || member.email || member.user_id.slice(0, 8);
}

function toggleId(ids: readonly string[], id: string): string[] {
  return ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id];
}

function samePoint(left: Point, right: Point): boolean {
  return left.every((value, index) => value === right[index]);
}

function safePhotoUrl(url: string): boolean {
  try {
    const protocol = new URL(url).protocol;
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

const PHOTO_FORMATS = new Set(["jpg", "jpeg", "png", "webp"]);

export function ModelCommentsPanel({
  client,
  versionId,
  workspaceId,
  canEdit,
  language,
  pendingPoint,
  onPickPoint,
  onClearPoint,
  onCommentsChange,
}: Props) {
  const ru = language === "ru";
  const [comments, setComments] = useState<ModelComment[]>([]);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [draft, setDraft] = useState("");
  const [mentions, setMentions] = useState<string[]>([]);
  const [replyTo, setReplyTo] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [replyMentions, setReplyMentions] = useState<string[]>([]);
  const [photoUrls, setPhotoUrls] = useState<Record<string, string>>({});
  const [photoTargetId, setPhotoTargetId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadRevision = useRef(0);
  const photoInput = useRef<HTMLInputElement>(null);

  const publish = useCallback((rows: ModelComment[]) => {
    setComments(rows);
    onCommentsChange(rows);
  }, [onCommentsChange]);

  const load = useCallback(async () => {
    if (!client || !versionId) {
      publish([]);
      setMembers([]);
      setLoaded(true);
      return;
    }
    const request = ++loadRevision.current;
    setError(null);
    const [commentsResult, membersResult] = await Promise.allSettled([
      client.listModelComments(versionId),
      client.listWorkspaceMembers(workspaceId),
    ]);
    if (loadRevision.current !== request) return;
    if (commentsResult.status === "fulfilled") {
      const rows = commentsResult.value;
      publish(rows);
      const assetIds = [...new Set(rows.flatMap((comment) => comment.photo_asset_ids ?? []))];
      const downloads = await Promise.allSettled(assetIds.map((assetId) => client.download(assetId)));
      if (loadRevision.current !== request) return;
      const nextUrls: Record<string, string> = {};
      downloads.forEach((result, index) => {
        const assetId = assetIds[index];
        if (
          assetId
          && result.status === "fulfilled"
          && result.value.asset_id === assetId
          && PHOTO_FORMATS.has((result.value.format ?? "").toLowerCase())
          && result.value.byte_size > 0
          && result.value.expires_in_seconds > 0
          && safePhotoUrl(result.value.url)
        ) {
          nextUrls[assetId] = result.value.url;
        }
      });
      setPhotoUrls(nextUrls);
    } else {
      publish([]);
      setError(commentsResult.reason instanceof Error ? commentsResult.reason.message : String(commentsResult.reason));
    }
    setMembers(membersResult.status === "fulfilled" ? membersResult.value : []);
    setLoaded(true);
  }, [client, publish, versionId, workspaceId]);

  useEffect(() => {
    setLoaded(false);
    setBusy(false);
    setDraft("");
    setMentions([]);
    setReplyTo(null);
    setReply("");
    setReplyMentions([]);
    setPhotoUrls({});
    setPhotoTargetId(null);
    onClearPoint();
    void load();
    return () => { loadRevision.current += 1; };
  }, [load, onClearPoint]);

  async function reloadAfterConflict(reason: unknown) {
    if (reason instanceof ApiError && reason.status === 409) {
      await load();
      setError(ru ? "Обсуждение изменилось у коллеги. Загружена свежая версия." : "A teammate changed the discussion. The latest version was loaded.");
      return true;
    }
    return false;
  }

  async function createRoot() {
    const text = draft.trim();
    if (!client || !versionId || !pendingPoint || !text || busy) return;
    const request = loadRevision.current;
    const targetVersionId = versionId;
    setBusy(true);
    setError(null);
    try {
      const saved = await client.createModelComment(versionId, text, pendingPoint, mentions);
      if (loadRevision.current !== request) return;
      if (
        saved.version_id !== targetVersionId
        || saved.parent_comment_id !== null
        || !samePoint(saved.point_mm, pendingPoint)
      ) {
        throw new Error(ru ? "Сервер вернул комментарий для другой точки или версии." : "The server returned a comment for another point or version.");
      }
      publish([...comments, saved]);
      setDraft("");
      setMentions([]);
      onClearPoint();
    } catch (reason) {
      if (!(await reloadAfterConflict(reason))) setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function toggleStatus(comment: ModelComment) {
    if (!client || busy) return;
    const request = loadRevision.current;
    setBusy(true);
    setError(null);
    try {
      const saved = await client.updateModelComment(
        comment.id,
        comment.comment,
        comment.status === "open" ? "resolved" : "open",
        comment.revision,
        comment.mentioned_user_ids ?? [],
      );
      if (loadRevision.current !== request) return;
      if (saved.id !== comment.id || saved.version_id !== comment.version_id) {
        throw new Error(ru ? "Сервер вернул другое обсуждение." : "The server returned another discussion.");
      }
      publish(comments.map((row) => row.id === saved.id ? saved : row));
    } catch (reason) {
      if (!(await reloadAfterConflict(reason))) setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function createReply(root: ModelComment) {
    const text = reply.trim();
    if (!client || !text || busy) return;
    const request = loadRevision.current;
    setBusy(true);
    setError(null);
    try {
      const saved = await client.createModelCommentReply(root.id, text, replyMentions);
      if (loadRevision.current !== request) return;
      if (saved.parent_comment_id !== root.id || saved.version_id !== root.version_id) {
        throw new Error(ru ? "Сервер вернул ответ из другой ветки." : "The server returned a reply from another thread.");
      }
      publish([...comments, saved]);
      setReplyTo(null);
      setReply("");
      setReplyMentions([]);
    } catch (reason) {
      if (!(await reloadAfterConflict(reason))) setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  function choosePhoto(comment: ModelComment) {
    if ((comment.photo_asset_ids ?? []).length >= 10 || busy) return;
    setPhotoTargetId(comment.id);
    photoInput.current?.click();
  }

  async function attachPhoto(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    const target = comments.find((comment) => comment.id === photoTargetId);
    setPhotoTargetId(null);
    if (!client || !file || !target || busy) return;
    if (!new Set(["image/jpeg", "image/png", "image/webp"]).has(file.type)) {
      setError(ru ? "Поддерживаются JPEG, PNG и WebP." : "JPEG, PNG, and WebP are supported.");
      return;
    }
    const request = loadRevision.current;
    setBusy(true);
    setError(null);
    try {
      const asset = await client.uploadFile(workspaceId, file, file.name, file.type);
      if (loadRevision.current !== request) return;
      if (asset.workspace_id !== workspaceId || !asset.mime.startsWith("image/") || asset.byte_size <= 0) {
        throw new Error(ru ? "Загрузка вернула неподходящий файл." : "The upload returned an invalid file.");
      }
      const saved = await client.addModelCommentPhoto(target.id, asset.id, target.revision);
      if (loadRevision.current !== request) return;
      if (
        saved.id !== target.id
        || saved.version_id !== target.version_id
        || !(saved.photo_asset_ids ?? []).includes(asset.id)
      ) {
        throw new Error(ru ? "Сервер не подтвердил вложение." : "The server did not confirm the attachment.");
      }
      await load();
    } catch (reason) {
      if (!(await reloadAfterConflict(reason))) setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function removePhoto(comment: ModelComment, assetId: string) {
    if (!client || busy) return;
    const request = loadRevision.current;
    setBusy(true);
    setError(null);
    try {
      const saved = await client.removeModelCommentPhoto(comment.id, assetId, comment.revision);
      if (loadRevision.current !== request) return;
      if (
        saved.id !== comment.id
        || saved.version_id !== comment.version_id
        || (saved.photo_asset_ids ?? []).includes(assetId)
      ) {
        throw new Error(ru ? "Сервер не подтвердил удаление вложения." : "The server did not confirm attachment removal.");
      }
      await load();
    } catch (reason) {
      if (!(await reloadAfterConflict(reason))) setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  const roots = comments.filter((comment) => comment.parent_comment_id === null);
  const memberName = new Map(members.map((member) => [member.user_id, mentionLabel(member)]));
  const mentionPicker = (selected: string[], change: (ids: string[]) => void) => members.length ? (
    <div className="row" style={{ flexWrap: "wrap" }}>
      {members.map((member) => (
        <button
          key={member.user_id}
          type="button"
          className={`chip ${selected.includes(member.user_id) ? "active" : ""}`}
          aria-pressed={selected.includes(member.user_id)}
          onClick={() => change(toggleId(selected, member.user_id))}
        >
          @{mentionLabel(member)}
        </button>
      ))}
    </div>
  ) : null;

  if (!loaded) return <span className="muted">{ru ? "Загружаем обсуждение…" : "Loading discussion…"}</span>;

  return (
    <div className="stack" data-version-id={versionId ?? undefined}>
      <input ref={photoInput} type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={(event) => void attachPhoto(event)} />
      {error && <div className="error">{error}</div>}
      <span className="muted">{ru
        ? "Каждая ветка привязана к точке и точной неизменяемой версии модели."
        : "Every thread is bound to one point and one exact immutable model version."}</span>
      {canEdit ? (
        <div className="card stack">
          <button className={`btn ${pendingPoint ? "active" : ""}`} type="button" onClick={onPickPoint} disabled={busy}>
            {pendingPoint
              ? `${ru ? "Точка" : "Point"}: ${pendingPoint.map((value) => value.toFixed(1)).join(", ")} mm`
              : (ru ? "Выбрать точку на модели" : "Pick a point on the model")}
          </button>
          <textarea className="input" rows={3} value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={ru ? "Комментарий к этой точке" : "Comment at this point"} />
          {mentionPicker(mentions, setMentions)}
          <button className="btn primary" type="button" disabled={busy || !pendingPoint || !draft.trim()} onClick={() => void createRoot()}>
            {ru ? "Создать ветку" : "Create thread"}
          </button>
        </div>
      ) : <span className="muted">{ru ? "У вас доступ только для чтения." : "You have read-only access."}</span>}

      {roots.map((root) => {
        const replies = comments.filter((comment) => comment.parent_comment_id === root.id);
        return (
          <article className="card stack" key={root.id} style={{ opacity: root.status === "resolved" ? 0.7 : 1 }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>{root.author_name || (ru ? "Участник" : "Member")}</strong>
              <span className={`chip status-${root.status === "open" ? "yellow" : "green"}`}>{root.status === "open" ? (ru ? "Открыто" : "Open") : (ru ? "Решено" : "Resolved")}</span>
            </div>
            <span>{root.comment}</span>
            <span className="muted">{root.point_mm.map((value) => value.toFixed(1)).join(" × ")} mm</span>
            {(root.mentioned_user_ids ?? []).length > 0 && <span className="muted">{(root.mentioned_user_ids ?? []).map((id) => `@${memberName.get(id) ?? id.slice(0, 8)}`).join(" ")}</span>}
            {(root.photo_asset_ids ?? []).length > 0 && (
              <div className="row" style={{ flexWrap: "wrap" }}>
                {(root.photo_asset_ids ?? []).map((assetId) => (
                  <div className="stack" key={assetId} style={{ maxWidth: 180 }}>
                    {photoUrls[assetId]
                      ? <img src={photoUrls[assetId]} alt={ru ? "Фото к комментарию" : "Comment attachment"} style={{ width: "100%", borderRadius: 12 }} />
                      : <span className="muted">{ru ? "Фото недоступно" : "Photo unavailable"}</span>}
                    {canEdit && <button className="btn" type="button" disabled={busy} onClick={() => void removePhoto(root, assetId)}>{ru ? "Удалить фото" : "Remove photo"}</button>}
                  </div>
                ))}
              </div>
            )}
            {replies.map((item) => (
              <div key={item.id} className="stack" style={{ borderLeft: "2px solid var(--border)", paddingLeft: 12 }}>
                <strong>{item.author_name || (ru ? "Участник" : "Member")}</strong>
                <span>{item.comment}</span>
                {(item.mentioned_user_ids ?? []).length > 0 && <span className="muted">{(item.mentioned_user_ids ?? []).map((id) => `@${memberName.get(id) ?? id.slice(0, 8)}`).join(" ")}</span>}
              </div>
            ))}
            {canEdit && (
              <div className="row" style={{ flexWrap: "wrap" }}>
                <button className="btn" type="button" disabled={busy} onClick={() => void toggleStatus(root)}>{root.status === "open" ? (ru ? "Отметить решённым" : "Resolve") : (ru ? "Открыть снова" : "Reopen")}</button>
                <button className="btn" type="button" disabled={busy} onClick={() => { setReplyTo(replyTo === root.id ? null : root.id); setReply(""); setReplyMentions([]); }}>{ru ? "Ответить" : "Reply"}</button>
                <button className="btn" type="button" disabled={busy || (root.photo_asset_ids ?? []).length >= 10} onClick={() => choosePhoto(root)}>{ru ? `+ Фото · ${(root.photo_asset_ids ?? []).length}/10` : `+ Photo · ${(root.photo_asset_ids ?? []).length}/10`}</button>
              </div>
            )}
            {replyTo === root.id && (
              <div className="stack">
                <textarea className="input" rows={2} value={reply} onChange={(event) => setReply(event.target.value)} placeholder={ru ? "Ответ в этой ветке" : "Reply in this thread"} />
                {mentionPicker(replyMentions, setReplyMentions)}
                <button className="btn primary" type="button" disabled={busy || !reply.trim()} onClick={() => void createReply(root)}>{ru ? "Отправить ответ" : "Send reply"}</button>
              </div>
            )}
          </article>
        );
      })}
      {roots.length === 0 && <span className="muted">{ru ? "На этой версии обсуждений пока нет." : "This version has no discussion yet."}</span>}
    </div>
  );
}
