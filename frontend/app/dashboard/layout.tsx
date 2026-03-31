import type { ReactNode } from "react";

import { ApprovalModal } from "@/components/approval/ApprovalModal";

interface DashboardLayoutProps {
  children: ReactNode;
}

export default function DashboardLayout({ children }: DashboardLayoutProps) {
  return (
    <div className="min-h-screen bg-dashboard-grid bg-[size:40px_40px]">
      {children}
      <ApprovalModal />
    </div>
  );
}

