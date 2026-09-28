"use client";

import { ReactNode } from "react";
import { ShellProvider, useShell } from "./ShellContext";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";

function ShellInner({ children }: { children: ReactNode }) {
  const { collapsed, mobileOpen, closeMobile } = useShell();
  return (
    <div className={`shell${collapsed ? " collapsed" : ""}`}>
      <div className={`backdrop${mobileOpen ? " show" : ""}`} onClick={closeMobile} />
      <Sidebar />
      <div className="main">
        <TopBar />
        <main className="content">{children}</main>
        <footer className="note">Oracle X — AI cross-market alpha engine</footer>
      </div>
    </div>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  return (
    <ShellProvider>
      <ShellInner>{children}</ShellInner>
    </ShellProvider>
  );
}
