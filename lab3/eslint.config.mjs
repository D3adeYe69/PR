import eslint from "@eslint/js";
import tseslint from 'typescript-eslint';
import jsdoc from "eslint-plugin-jsdoc";
import tsParser from "@typescript-eslint/parser";

export default tseslint.config(
    {
        ignores: [
            "eslint.*",
            "**/node_modules", 
            "**/dist", 
            "**/coverage", 
            "**/test", 
        ],
    }, 
    {
        files: ["**/*.ts"],
        linterOptions: {
            // don't allow comments in source files to suppress eslint comments
            noInlineConfig: true,
        },
        languageOptions: {
            parser: tsParser,
            ecmaVersion: 5,
            sourceType: "script",

            parserOptions: {
                project: ["./tsconfig.json"],
            },
        },

        // start with some base recommended rules
        extends: [
            eslint.configs.recommended, // https://eslint.org/docs/rules/
            tseslint.configs.recommendedTypeChecked, // https://typescript-eslint.io/rules/ (filter for "recommended")

            // using rules from eslint-plugin-jsdoc in preference to eslint-plugin-tsdoc, because tsdoc is too rigid
            // (e.g. it assumes the doc comment is HTML instead of markdown, and warns about < and <=)
            jsdoc.configs['flat/recommended-typescript'], 
                        // https://github.com/gajus/eslint-plugin-jsdoc?tab=readme-ov-file#user-content-eslint-plugin-jsdoc-rules,
        ],

        // configure the recommended rules for 6.102
        rules: {
            // in the config below
            //    error means that Caesar will show a comment marked #important
            //    warn means that Caesar will show a comment, but without #important
            //    off means eslint and Caesar won't report the issue

            "no-tabs": "error",
            "max-lines": ["warn", 2000],
            "max-params": ["warn", 7],
            "max-lines-per-function": ["warn", 150],
            "max-depth": ["warn", 4],
            "no-warning-comments": "warn", // catches TODO
            "semi": "error", // require semicolons ending statements

            "@typescript-eslint/naming-convention": ["error", {
                // allow UPPER_CASE enum members
                selector: "enumMember",
                format: ["UPPER_CASE", "camelCase", "PascalCase"],
            }, 
            // ...and the rest is just restating the naming - convention defaults(which is necessary
            // because overriding this option erases the default naming convention rules and replaces them with these rules)
            {
                selector: "default",
                format: ["camelCase"],
                leadingUnderscore: "allow",
                trailingUnderscore: "allow",
            }, {
                selector: "variable",
                format: ["camelCase", "UPPER_CASE"],
                leadingUnderscore: "allow",
                trailingUnderscore: "allow",
            }, {
                selector: "typeLike",
                format: ["PascalCase"],
            }],

            // extra TS requirements
            "@typescript-eslint/explicit-function-return-type": ["error", {
                allowExpressions: true,
            }],
            "@typescript-eslint/explicit-member-accessibility": "error",
            "@typescript-eslint/no-inferrable-types": "warn",
            "@typescript-eslint/no-for-in-array": "error",
            "@typescript-eslint/prefer-for-of": "warn",
            "@typescript-eslint/no-unsafe-argument": "warn",
            "@typescript-eslint/prefer-nullish-coalescing": "warn",
            "@typescript-eslint/prefer-readonly": "error",
            "@typescript-eslint/strict-boolean-expressions": "error",
            "@typescript-eslint/no-unnecessary-boolean-literal-compare": "error",
            "@typescript-eslint/switch-exhaustiveness-check": "error",
            "@typescript-eslint/no-non-null-assertion": "error",

            // configure jsdoc plugin to match the way we use TypeDoc
            "jsdoc/no-types": "error", // forbid types in @param, because they're redundant with TS declaration
            "jsdoc/require-param-type": "off", // ditto
            "jsdoc/require-returns-type": "off", // ditto
            "jsdoc/tag-lines": "off", // too picky about spacing
            "jsdoc/check-tag-names": ["warn", { 
                "definedTags": [ "typeParam" ]  // allowed in TypeDoc but unknown in JSDoc 
            }],

            "no-constant-condition": "off", // so that we can say "while (true) {...}" without error
            "@typescript-eslint/no-base-to-string": "off", // incorrect e.g. when an interface omits toString()
            "@typescript-eslint/no-unused-vars": "off", // TS compiler already shows this warning
            "@typescript-eslint/restrict-plus-operands": "off", // template literals are good but we don't introduce them right away
            "@typescript-eslint/restrict-template-expressions": "off", // template literals should be allowed to have non-string fields
            "@typescript-eslint/require-await": "off", // async functions should be allowed to have no awaits in them

            // configure magic numbers a bit
            "no-magic-numbers": ["error", {
                ignore: [0, 1, 2, -1, -2],
            }],

            // disallow typecasts like "expr as <T>"
            "@typescript-eslint/consistent-type-assertions": [ "error", { assertionStyle: "never" }],

        },
    },
    {
        // turn off magic-number checking in tests
        files: ["**/test/**"],
        rules: {
            "no-magic-numbers": "off",
        },
    }
);
