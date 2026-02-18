import { useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useStore } from './hooks/useStore';
import { getMcpServers, getBuiltinTools } from './utils/api';
import ProjectList from './components/ProjectList';
import ProjectEditor from './components/ProjectEditor';

function App() {
  const { setMcpServers, setBuiltinTools } = useStore();
  
  // Load reference data on mount
  useEffect(() => {
    getMcpServers().then(setMcpServers).catch(console.error);
    getBuiltinTools().then(setBuiltinTools).catch(console.error);
  }, [setMcpServers, setBuiltinTools]);
  
  return (
    <Routes>
      <Route path="/" element={<ProjectList />} />
      <Route path="/project/:projectId" element={<ProjectEditor />} />
      <Route path="/project/:projectId/:tab" element={<ProjectEditor />} />
      <Route path="/project/:projectId/:tab/:itemId" element={<ProjectEditor />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;

