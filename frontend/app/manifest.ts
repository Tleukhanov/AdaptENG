import type { MetadataRoute } from 'next';

/**
 * Web app manifest (served as /manifest.webmanifest by the App Router).
 *
 * Kept in the app directory so the URL is stable in the standalone build and
 * the manifest is linked from every page automatically.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'AdaptENG — AI English Tutor',
    short_name: 'AdaptENG',
    description: 'Adaptive AI English tutor with personality characters.',
    start_url: '/',
    scope: '/',
    display: 'standalone',
    orientation: 'portrait',
    theme_color: '#0b1220',
    background_color: '#0b1220',
    lang: 'ru',
    categories: ['education', 'productivity'],
    icons: [
      {
        src: '/icons/icon-192.png',
        sizes: '192x192',
        type: 'image/png',
        purpose: 'any',
      },
      {
        src: '/icons/icon-512.png',
        sizes: '512x512',
        type: 'image/png',
        purpose: 'any',
      },
    ],
  };
}
