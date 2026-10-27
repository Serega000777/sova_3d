import { File, Paths } from "expo-file-system";
import { isAvailableAsync, shareAsync } from "expo-sharing";

export interface IntegrityPdfClient {
  downloadIntegrityReport(versionId: string): Promise<Blob>;
}

/** Keep the authenticated response private, materialize it locally, then invoke native sharing. */
export async function shareIntegrityReportPdf(
  client: IntegrityPdfClient,
  versionId: string,
): Promise<void> {
  if (!(await isAvailableAsync())) {
    throw new Error("Native file sharing is unavailable on this device.");
  }
  const document = await client.downloadIntegrityReport(versionId);
  if (document.type !== "application/pdf") {
    throw new Error("The server did not return a PDF integrity report.");
  }
  const file = new File(Paths.cache, `sova-integrity-${versionId}.pdf`);
  file.create({ overwrite: true, intermediates: true });
  file.write(new Uint8Array(await document.arrayBuffer()));
  await shareAsync(file.uri, {
    mimeType: "application/pdf",
    UTI: "com.adobe.pdf",
    dialogTitle: "Sova 3D integrity report",
  });
}
