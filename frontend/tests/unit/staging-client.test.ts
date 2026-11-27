import { expect, it } from "vitest";
import { isUnconfirmedStagingWrite, stagingError } from "@/lib/api/staging-client";
import { AuthError } from "@/lib/auth/browser-client";

it.each([408, 500, 502])("preserves the request ID for an unconfirmed HTTP %i response", (status) => {
  const error = new AuthError(status, undefined, undefined, undefined, "fixture-unconfirmed-write");
  expect(isUnconfirmedStagingWrite(error)).toBe(true);
  expect(stagingError(error, "The action could not be confirmed."))
    .toBe("The action could not be confirmed. Request ID fixture-unconfirmed-write.");
});
