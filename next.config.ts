import type { NextConfig } from 'next';
import createNextIntlPlugin from 'next-intl/plugin';

const withNextIntl = createNextIntlPlugin();

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Heroku/deploy: минимальный образ + запуск одним процессом (standalone).
  output: 'standalone',
};

export default withNextIntl(nextConfig);
