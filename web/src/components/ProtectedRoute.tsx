import { useAuth } from "@clerk/react";
import { Navigate, Outlet } from "react-router-dom";

export function ProtectedRoute() {
  const { isLoaded, isSignedIn } = useAuth();

  if (!isLoaded) {
    return <main className="auth-screen" aria-busy="true" />;
  }
  if (!isSignedIn) {
    return <Navigate to="/sign-in" replace />;
  }
  return <Outlet />;
}
