import { SignUp } from "@clerk/react";

export function SignUpPage() {
  return (
    <main className="auth-screen">
      <SignUp routing="path" path="/sign-up" signInUrl="/sign-in" />
    </main>
  );
}
