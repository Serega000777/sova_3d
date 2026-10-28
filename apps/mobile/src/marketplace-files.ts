import { File, Paths } from "expo-file-system";
import { isAvailableAsync, shareAsync } from "expo-sharing";

export const HOUSE_PDF_MIME = "application/pdf";
export const HOUSE_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
export const SOVA_PACKAGE_MIME = "application/vnd.sova.project+zip";

interface MarketplaceFileClient {
  downloadHouseDocument(listingId: string): Promise<Blob>;
  downloadHouseSpreadsheet(listingId: string): Promise<Blob>;
  downloadOrderSovaPackage(orderId: string): Promise<Blob>;
}

interface SharedMarketplaceFile {
  blob: Blob;
  fileName: string;
  mimeType: string;
  uti: string;
  dialogTitle: string;
}

function verifiedBlob(blob: Blob, expectedMime: string): Blob | null {
  const mime = blob.type.split(";", 1)[0]?.trim().toLowerCase();
  return blob.size > 0 && mime === expectedMime ? blob : null;
}

async function shareMarketplaceFile(value: SharedMarketplaceFile): Promise<void> {
  if (!(await isAvailableAsync())) {
    throw new Error("Системное меню файлов недоступно на этом устройстве.");
  }
  const blob = verifiedBlob(value.blob, value.mimeType);
  if (!blob) {
    throw new Error("Сервер вернул пустой файл или неожиданный формат.");
  }
  const file = new File(Paths.cache, value.fileName);
  file.create({ overwrite: true, intermediates: true });
  file.write(new Uint8Array(await blob.arrayBuffer()));
  await shareAsync(file.uri, {
    mimeType: value.mimeType,
    UTI: value.uti,
    dialogTitle: value.dialogTitle,
  });
}

/** Share the authenticated, server-rendered passport for one immutable house listing. */
export async function shareHouseDocument(
  client: MarketplaceFileClient,
  listingId: string,
): Promise<void> {
  await shareMarketplaceFile({
    blob: await client.downloadHouseDocument(listingId),
    fileName: `sova-house-${listingId}.pdf`,
    mimeType: HOUSE_PDF_MIME,
    uti: "com.adobe.pdf",
    dialogTitle: "Паспорт дома Sova 3D",
  });
}

/** Share the authenticated, server-rendered schedule for one immutable house listing. */
export async function shareHouseSpreadsheet(
  client: MarketplaceFileClient,
  listingId: string,
): Promise<void> {
  await shareMarketplaceFile({
    blob: await client.downloadHouseSpreadsheet(listingId),
    fileName: `sova-house-${listingId}.xlsx`,
    mimeType: HOUSE_XLSX_MIME,
    uti: "org.openxmlformats.spreadsheetml.sheet",
    dialogTitle: "Ведомость дома Sova 3D",
  });
}

/** Share the buyer-only editable package for the exact completed marketplace order. */
export async function shareOrderSovaPackage(
  client: MarketplaceFileClient,
  orderId: string,
): Promise<void> {
  await shareMarketplaceFile({
    blob: await client.downloadOrderSovaPackage(orderId),
    fileName: `sova-project-${orderId}.sova`,
    mimeType: SOVA_PACKAGE_MIME,
    uti: "public.zip-archive",
    dialogTitle: "Редактируемый проект Sova 3D",
  });
}
