import { Link, Outlet, useLocation } from "react-router-dom";
import PipelineBanner from "./PipelineBanner";

const groups = [
  {
    label: "工作",
    items: [
      { to: "/", label: "我的工作台" },
      { to: "/tasks/new", label: "制度对照检查" },
      { to: "/single-audit", label: "单份制度体检" },
    ],
  },
  {
    label: "资料与记录",
    items: [
      { to: "/library", label: "制度文件" },
      { to: "/records", label: "处理记录" },
    ],
  },
];

export default function Layout() {
  const loc = useLocation();
  const isActive = (to: string) =>
    to === "/" ? loc.pathname === "/" : loc.pathname === to || loc.pathname.startsWith(to + "/");

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand-row">
          <div className="brand-mark">审</div>
          <div>
            <div className="brand">制度审查工作台</div>
            <div className="sub">让制度问题更容易发现和处理</div>
          </div>
        </div>

        <nav className="nav">
          {groups.map((g) => (
            <div className="nav-group" key={g.label}>
              <div className="nav-section">{g.label}</div>
              {g.items.map((n) => (
                <Link key={n.to} to={n.to} className={isActive(n.to) ? "active" : ""}>
                  {n.label}
                </Link>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-foot">
          <span className="status-dot" />
          自动检查，人工把关
        </div>
      </aside>
      <div className="main">
        <PipelineBanner />
        <Outlet />
      </div>
    </div>
  );
}
