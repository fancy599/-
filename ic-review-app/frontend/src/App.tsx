import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import DiffDetail from "./pages/DiffDetail";
import Home from "./pages/Home";
import Library from "./pages/Library";
import Records from "./pages/Records";
import SingleAudit from "./pages/SingleAudit";
import TaskCreate from "./pages/TaskCreate";
import TaskDetail from "./pages/TaskDetail";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="library" element={<Library />} />
        <Route path="tasks/new" element={<TaskCreate />} />
        <Route path="single-audit" element={<SingleAudit />} />
        <Route path="tasks/:id" element={<TaskDetail />} />
        <Route path="diffs/:id" element={<DiffDetail />} />
        <Route path="records" element={<Records />} />
      </Route>
    </Routes>
  );
}
