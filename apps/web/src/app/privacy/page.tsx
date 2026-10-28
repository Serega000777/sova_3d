import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Политика конфиденциальности · Sova 3D",
};

export default function PrivacyPage() {
  return (
    <article className="stack" style={{ maxWidth: 820, margin: "0 auto" }}>
      <div className="card stack">
        <span className="chip" style={{ alignSelf: "flex-start" }}>Редакция от 29 октября 2026</span>
        <h1 style={{ margin: 0 }}>Политика конфиденциальности Sova 3D</h1>
        <p className="muted">
          Эта страница описывает данные, которые Sova 3D обрабатывает для создания, хранения,
          анализа и публикации 3D-проектов. Английское описание следует русскому; при расхождении
          применяется версия, указанная в карточке приложения для вашего региона.
        </p>
      </div>

      <section className="card stack">
        <h2>Какие данные обрабатываются</h2>
        <ul className="list">
          <li>Данные аккаунта: email, телефон или идентификатор выбранного провайдера входа, имя и язык.</li>
          <li>Пользовательский контент: фотографии, видео, сканы, 3D-модели, чертежи, команды и комментарии.</li>
          <li>Технические данные: устройство, версия приложения, IP-адрес, журналы ошибок и событий безопасности.</li>
          <li>Данные операций: рабочие пространства, права доступа, экспорт, покупки и лицензии маркетплейса.</li>
        </ul>
      </section>

      <section className="card stack">
        <h2>Зачем и кому передаются данные</h2>
        <p className="muted">
          Данные используются для входа, синхронизации, обработки 3D, поддержки, безопасности,
          выполнения покупок и соблюдения закона. Они передаются только поставщикам инфраструктуры,
          обработки и платежей в объёме, необходимом для работы функции. Sova 3D не продаёт персональные данные.
          Публичными становятся только материалы, которые пользователь сам отправил на публикацию.
        </p>
      </section>

      <section className="card stack">
        <h2>Хранение, обучение и удаление</h2>
        <p className="muted">
          Проектные данные хранятся, пока существует аккаунт или пока они нужны для запрошенной функции.
          Использование проектов для обучения отключено по умолчанию и включается только отдельным согласием.
          После запроса удаления способы входа отключаются сразу, а связанные данные удаляются в течение 30 дней,
          кроме записей, обязательный срок хранения которых установлен законом.
        </p>
        <Link href="/delete-account">Инструкция по удалению аккаунта</Link>
      </section>

      <section className="card stack">
        <h2>Your privacy</h2>
        <p className="muted">
          Sova 3D processes account identifiers, user-created 3D content, device and security logs,
          workspace permissions, exports, purchases and licences to provide and secure the service.
          Projects are not used for model training unless you give separate opt-in consent. We do not
          sell personal data. Account access is disabled immediately after a deletion request and
          associated data is erased within 30 days, subject to legally required retention.
        </p>
      </section>

      <p className="muted">
        Контакт правообладателя и адрес для обращений публикуются в карточке приложения и должны быть
        добавлены сюда до отправки релизной сборки в магазин.
      </p>
    </article>
  );
}
