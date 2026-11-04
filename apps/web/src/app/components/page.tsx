"use client";

import type { Component } from "@physical-ai/contracts";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { LoadingScreen } from "@/components/LoadingScreen";
import {
  type ComponentCategory,
  componentKindLabel,
  componentLibraryView,
} from "@/lib/component-library";
import { useSession } from "@/lib/session";

const CATEGORIES: ComponentCategory[] = ["all", "favorites", "electronics", "mechanics"];

export default function ComponentsPage() {
  const router = useRouter();
  const { session, ready, client } = useSession();
  const language: "ru" | "en" =
    typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("ru")
      ? "ru"
      : "en";
  const ru = language === "ru";
  const [components, setComponents] = useState<Component[]>([]);
  const [favoriteIds, setFavoriteIds] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<ComponentCategory>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loadRevision = useRef(0);
  const visible = useMemo(
    () => componentLibraryView(components, query, category, favoriteIds),
    [category, components, favoriteIds, query],
  );
  const selected = visible.find((component) => component.id === selectedId) ?? visible[0] ?? null;

  const load = useCallback(async () => {
    if (!client) return;
    const request = ++loadRevision.current;
    setError(null);
    try {
      const [rows, favorites] = await Promise.all([
        client.listComponents(undefined, language),
        client.listComponentFavorites(),
      ]);
      if (loadRevision.current !== request) return;
      setComponents(rows);
      setFavoriteIds(new Set(favorites.component_ids));
      setSelectedId((current) => current && rows.some((row) => row.id === current) ? current : rows[0]?.id ?? null);
      setLoaded(true);
    } catch (reason) {
      if (loadRevision.current === request) {
        setError(reason instanceof Error ? reason.message : String(reason));
        setLoaded(true);
      }
    }
  }, [client, language]);

  useEffect(() => {
    setLoaded(false);
    void load();
    return () => { loadRevision.current += 1; };
  }, [load]);

  async function toggleFavorite(componentId: string) {
    if (!client || busy) return;
    const wasFavorite = favoriteIds.has(componentId);
    setFavoriteIds((current) => {
      const next = new Set(current);
      if (wasFavorite) next.delete(componentId);
      else next.add(componentId);
      return next;
    });
    setBusy(`favorite:${componentId}`);
    setError(null);
    try {
      if (wasFavorite) await client.removeComponentFavorite(componentId);
      else await client.addComponentFavorite(componentId);
    } catch (reason) {
      setFavoriteIds((current) => {
        const next = new Set(current);
        if (wasFavorite) next.add(componentId);
        else next.delete(componentId);
        return next;
      });
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function createMountingModel() {
    if (!client || !session || !selected || busy) return;
    const sourceId = selected.id;
    setBusy(`model:${sourceId}`);
    setError(null);
    try {
      const accepted = await client.createComponentModel(sourceId, {
        workspace_id: session.workspaceId,
      });
      if (
        accepted.component_id !== sourceId
        || accepted.model_scope !== "mounting_geometry"
        || !accepted.project_id
      ) {
        throw new Error(ru ? "Сервер вернул модель другого компонента." : "The server returned a model for another component.");
      }
      const job = await client.waitForJob(accepted.job.job_id, {
        onProgress: (update) => setBusy(`model:${sourceId}:${update.progress}`),
      });
      if (job.status !== "succeeded" || job.project_id !== accepted.project_id) {
        const detail = job.error as { message?: string } | null;
        throw new Error(detail?.message ?? (ru ? "Монтажную модель не удалось построить." : "The mounting model did not build."));
      }
      router.push(`/projects/${accepted.project_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  if (!ready) return <LoadingScreen />;
  if (!session) {
    return <div className="empty-stage"><Link className="btn primary" href="/login">{ru ? "Войти" : "Sign in"}</Link></div>;
  }
  if (!loaded) return <LoadingScreen />;

  const categoryLabel = (item: ComponentCategory) => ({
    all: ru ? "Все" : "All",
    favorites: ru ? "Избранное" : "Favorites",
    electronics: ru ? "Электроника" : "Electronics",
    mechanics: ru ? "Механика" : "Mechanics",
  })[item];

  return (
    <div className="stack" style={{ maxWidth: 1050 }}>
      <div>
        <h1 style={{ margin: 0 }}>{ru ? "Инженерные компоненты" : "Engineering components"}</h1>
        <span className="muted">{ru ? "Проверенные габариты, крепёж и монтажная геометрия — без выдуманного внешнего вида." : "Verified envelopes, fasteners, and mounting geometry — without an invented product exterior."}</span>
      </div>
      {error && <div className="error">{error}</div>}
      <div className="row" style={{ flexWrap: "wrap" }}>
        <input
          className="input"
          type="search"
          value={query}
          placeholder={ru ? "Название, тип или крепёж" : "Name, type, or fastener"}
          aria-label={ru ? "Поиск компонентов" : "Search components"}
          onChange={(event) => setQuery(event.target.value)}
          style={{ flex: 1, minWidth: 240 }}
        />
        <div className="segmented compact" role="group" aria-label={ru ? "Категория" : "Category"}>
          {CATEGORIES.map((item) => (
            <button key={item} type="button" className={category === item ? "active" : ""} onClick={() => setCategory(item)}>
              {categoryLabel(item)}
            </button>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(280px, 1fr) minmax(300px, 1fr)", gap: 16, alignItems: "start" }}>
        <section className="stack">
          {visible.map((component) => (
            <div className="card stack" key={component.id} style={{ borderColor: selected?.id === component.id ? "var(--accent)" : undefined }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <button type="button" style={{ all: "unset", cursor: "pointer", flex: 1 }} onClick={() => setSelectedId(component.id)}>
                  <strong>{component.name}</strong>
                </button>
                <button
                  className="btn"
                  type="button"
                  disabled={Boolean(busy)}
                  aria-label={favoriteIds.has(component.id) ? (ru ? "Убрать из избранного" : "Remove favorite") : (ru ? "Добавить в избранное" : "Add favorite")}
                  onClick={() => void toggleFavorite(component.id)}
                >
                  {favoriteIds.has(component.id) ? "♥" : "♡"}
                </button>
              </div>
              <span className="muted">{componentKindLabel(component.kind, language)} · {component.size_mm.map((value) => value.toFixed(1)).join(" × ")} mm</span>
              <span className="muted">{component.note}</span>
            </div>
          ))}
          {visible.length === 0 && <div className="card muted">{ru ? "Компоненты не найдены." : "No components found."}</div>}
        </section>

        {selected && (
          <aside className="card stack" style={{ position: "sticky", top: 84 }}>
            <h2 style={{ margin: 0 }}>{selected.name}</h2>
            <span>{selected.size_mm.map((value) => value.toFixed(1)).join(" × ")} mm · {ru ? "высота" : "height"} {selected.height_mm.toFixed(1)} mm</span>
            <span className="muted">{selected.holes.length} {ru ? "монтажных отверстий" : "mounting holes"} · {ru ? "крепёж" : "fastener"} {selected.screw} · {selected.cutouts.length} {ru ? "вырезов" : "cutouts"}</span>
            <span className="muted">{ru ? "Источник размеров" : "Dimension source"}: {selected.confidence}</span>
            {selected.opening_mm && <span className="chip">{ru ? "Функциональное окно" : "Functional opening"}: {selected.opening_mm.join(" × ")} mm</span>}
            <span className="muted">{ru ? "Создаваемая CAD-модель сохраняет mounting envelope, основание, отверстия и функциональный вырез. Разъёмы, электроника и косметические поверхности не моделируются." : "The CAD output preserves the mounting envelope, base, holes, and functional opening. Connectors, electronics, and cosmetic surfaces are omitted."}</span>
            <button className="btn primary" type="button" disabled={Boolean(busy)} onClick={() => void createMountingModel()}>
              {busy?.startsWith(`model:${selected.id}`) ? (ru ? "Строим…" : "Building…") : (ru ? "Создать монтажную CAD-модель" : "Create mounting CAD model")}
            </button>
          </aside>
        )}
      </div>
    </div>
  );
}
