"use client";

import type { Cart } from "@physical-ai/contracts";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ListingCard } from "@/components/ListingCard";
import { LoadingScreen } from "@/components/LoadingScreen";
import { useSession } from "@/lib/session";

type Language = "en" | "ru";

export default function CartPage() {
  const { session, ready, client } = useSession();
  const [language, setLanguage] = useState<Language>("ru");
  const [cart, setCart] = useState<Cart | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ru = language === "ru";

  useEffect(() => {
    setLanguage(navigator.language.toLowerCase().startsWith("ru") ? "ru" : "en");
  }, []);

  const refresh = useCallback(async () => {
    if (!client || !session) return;
    setError(null);
    try {
      setCart(await client.getCart(session.workspaceId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [client, session]);

  useEffect(() => { void refresh(); }, [refresh]);

  async function remove(itemId: string) {
    if (!client || !session) return;
    setBusyId(itemId);
    try {
      await client.removeFromCart(itemId, session.workspaceId);
      await refresh();
    } finally {
      setBusyId(null);
    }
  }

  if (!ready) return <LoadingScreen />;
  if (!session) return <div className="card">{ru ? "Войдите, чтобы открыть корзину." : "Sign in to see your cart."}</div>;

  return (
    <div className="stack marketplace-cart">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <h1 style={{ margin: 0 }}>{ru ? "Корзина" : "Cart"}</h1>
          <span className="muted">{ru ? "Товары будут добавлены в текущее рабочее пространство." : "Items will land in the current workspace."}</span>
        </div>
        <Link className="btn" href="/market">{ru ? "Продолжить покупки" : "Keep browsing"}</Link>
      </div>
      {error && <div className="error">{error}</div>}
      {cart?.items.map((listing) => (
        <div className="marketplace-cart-row" key={listing.id}>
          <ListingCard listing={listing} language={language} layout="list" />
          <button className="btn" type="button" disabled={busyId === listing.id} onClick={() => void remove(listing.id)}>
            {busyId === listing.id ? (ru ? "Удаляю…" : "Removing…") : (ru ? "Удалить" : "Remove")}
          </button>
        </div>
      ))}
      {cart && cart.items.length === 0 && <div className="card muted">{ru ? "Корзина пуста." : "Your cart is empty."}</div>}
      <div className="card row marketplace-cart-total">
        <strong>{ru ? "Итого" : "Total"}: {((cart?.total_cents ?? 0) / 100).toFixed(2)} USD</strong>
        <button className="btn primary" type="button" disabled title={ru ? "Платёжный провайдер ещё не выбран" : "Payment provider is not selected yet"}>
          {ru ? "Оплата — скоро" : "Checkout — coming soon"}
        </button>
      </div>
    </div>
  );
}
