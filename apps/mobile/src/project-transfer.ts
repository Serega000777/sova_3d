import { ApiError } from "@physical-ai/contracts";

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/;

export type ProjectTransferRequest = {
  recipient_email: string;
  confirmation_name: string;
};

export function projectTransferRequest(
  recipientEmail: string,
  confirmationName: string,
  projectName: string,
): { body: ProjectTransferRequest; error: null } | { body: null; error: string } {
  const email = recipientEmail.trim().toLowerCase();
  if (!email) return { body: null, error: "Укажите email нового владельца." };
  if (email.length > 320 || !EMAIL.test(email)) {
    return { body: null, error: "Проверьте формат email нового владельца." };
  }
  if (confirmationName !== projectName) {
    return { body: null, error: "Введите точное название проекта для подтверждения." };
  }
  return {
    body: { recipient_email: email, confirmation_name: confirmationName },
    error: null,
  };
}

export function projectTransferError(reason: unknown): string {
  if (reason instanceof ApiError) {
    if (reason.status === 404) return "Проект недоступен или уже передан.";
    if (reason.status === 409) {
      return "Передача пока невозможна. Завершите активные задания, черновики и публикации проекта.";
    }
    if (reason.status === 422) return "Проверьте данные и доступность получателя.";
    return "Сервер не выполнил передачу проекта. Попробуйте ещё раз.";
  }
  return "Не удалось передать проект. Проверьте подключение и попробуйте ещё раз.";
}
