export declare function unprotectWindows(ciphertext: string): Promise<string>;
export declare function readLocalIntegrationToken(baseUrl: string, options?: {
    path?: string;
    decrypt?: (ciphertext: string) => Promise<string>;
}): Promise<string | null>;
//# sourceMappingURL=local_credentials.d.ts.map