// iPhone photos are HEIC/HEIF, which only Safari can draw. Photos in Photos and Files are turned
// into JPEG by the server, but vault photos are decrypted here in the browser and the server never
// sees them, so for those the decoding happens here too. The decoder is about 3 MB, so it is only
// downloaded the first time a HEIC photo needs it. ("heic-to/csp" is the build that works under
// ZiraHive's Content-Security-Policy: no eval, no WebAssembly.)

export const looksHeic = (name: string, type: string) =>
  /^image\/hei[cf]/i.test(type) || /\.(heic|heif)$/i.test(name);

/** The photo as a JPEG. Throws if it isn't a HEIC/HEIF image or is damaged. */
export async function heicToJpeg(blob: Blob): Promise<Blob> {
  const { heicTo } = await import("heic-to/csp");
  return heicTo({ blob, type: "image/jpeg", quality: 0.92 });
}

/** Something an <img> can show: the photo itself when this browser can draw it (Safari can draw
 * HEIC), otherwise a JPEG of it. */
export async function viewablePhoto(blob: Blob, name: string): Promise<Blob> {
  if (!looksHeic(name, blob.type)) return blob;
  try {
    (await createImageBitmap(blob)).close();
    return blob;
  } catch {
    return heicToJpeg(blob);
  }
}
