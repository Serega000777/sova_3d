"use client";

import type { Project } from "@physical-ai/contracts";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useSession } from "@/lib/session";

export default function ModelingPage() {
  const { session, ready, client } = useSession();
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!client || !session) return;
    void client.listProjects(session.workspaceId).then(setProjects).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : String(reason));
    });
  }, [client, session]);

  if (!ready) return null;
  if (!session) {
    return <div className="empty-stage"><h1>Моделлинг</h1><Link className="btn primary" href="/login">Войти и начать</Link></div>;
  }

  const active = projects.filter((project) => project.head_version_id);
  return (
    <div className="modeling-home">
      <section className="modeling-hero">
        <div>
          <span className="eyebrow">AI + ТОЧНАЯ ГЕОМЕТРИЯ</span>
          <h1>Рабочая область моделей</h1>
          <p>Создавайте с нуля инструментами, описывайте результат AI или продолжайте открытую модель.</p>
        </div>
        <Link href="/new" className="btn primary modeling-create">+ Создать модель</Link>
      </section>

      <section className="workflow-strip">
        <div><b>01</b><span>Идея, фото<br />или шаблон</span></div>
        <div><b>02</b><span>Эскизы<br />и варианты</span></div>
        <div><b>03</b><span>Редактирование<br />области + AI</span></div>
        <div><b>04</b><span>Проверка,<br />слайсинг, экспорт</span></div>
      </section>

      <div className="section-heading">
        <div><h2>Продолжить работу</h2><p className="muted">Нажмите на карточку — откроется полноценная рабочая область.</p></div>
        <Link href="/">Все проекты →</Link>
      </div>
      {error && <div className="error">{error}</div>}
      <div className="project-gallery">
        {active.slice(0, 8).map((project, index) => (
          <Link href={`/projects/${project.id}`} className="project-tile" key={project.id}>
            <div className={`project-preview preview-${index % 4}`}>
              <span className="model-glyph">{index % 3 === 0 ? "⬡" : index % 3 === 1 ? "◈" : "⌬"}</span>
              <span className="project-open">Открыть ↗</span>
            </div>
            <strong>{project.name}</strong>
            <span className="muted">Модель · {new Date(project.updated_at).toLocaleDateString("ru")}</span>
          </Link>
        ))}
        {active.length === 0 && (
          <Link href="/new" className="project-tile project-empty">
            <div className="project-preview"><span className="model-glyph">＋</span></div>
            <strong>Первая модель</strong><span className="muted">Начните с описания или шаблона</span>
          </Link>
        )}
      </div>
    </div>
  );
}
