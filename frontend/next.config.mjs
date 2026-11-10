const isDev = process.env.NODE_ENV === 'development';

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  images: { unoptimized: true },
  // Dev only: proxy /api/* to the FastAPI backend (rewrites are not part of a static export).
  ...(isDev
    ? {
        async rewrites() {
          return [{ source: '/api/:path*', destination: 'http://localhost:8000/api/:path*' }];
        },
      }
    : {}),
};

export default nextConfig;
