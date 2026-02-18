import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { execSync } from 'child_process'

// Get git info at build time
function getGitInfo() {
  try {
    const commit = execSync('git rev-parse HEAD').toString().trim()
    const commitShort = commit.slice(0, 7)
    const branch = execSync('git rev-parse --abbrev-ref HEAD').toString().trim()
    const commitDate = execSync('git log -1 --format=%ci').toString().trim()
    return { commit, commitShort, branch, commitDate }
  } catch {
    return { commit: 'unknown', commitShort: 'unknown', branch: 'unknown', commitDate: 'unknown' }
  }
}

const gitInfo = getGitInfo()

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(process.env.npm_package_version || '0.1.0'),
    __GIT_COMMIT__: JSON.stringify(gitInfo.commit),
    __GIT_COMMIT_SHORT__: JSON.stringify(gitInfo.commitShort),
    __GIT_BRANCH__: JSON.stringify(gitInfo.branch),
    __GIT_COMMIT_DATE__: JSON.stringify(gitInfo.commitDate),
    __BUILD_TIME__: JSON.stringify(new Date().toISOString()),
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8080',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    // Ensure proper paths for production
    rollupOptions: {
      output: {
        manualChunks: undefined,
      },
    },
  },
})

