import createNextIntlPlugin from 'next-intl/plugin';

const withNextIntl = createNextIntlPlugin();

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Heroku: минимальный образ + запуск одним процессом (standalone).
  output: 'standalone',
};

export default withNextIntl(nextConfig);