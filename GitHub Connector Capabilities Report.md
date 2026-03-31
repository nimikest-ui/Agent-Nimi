# GitHub Connector Capabilities Report

This report outlines the capabilities of the GitHub connector, demonstrated through the `gh` CLI tool, and presents sample data fetched from GitHub.

## Connector Capabilities Overview

The GitHub connector, accessible via the `gh` command-line interface, provides a robust way to interact with GitHub repositories, user profiles, issues, pull requests, and more. It allows for:

*   **Authentication Management**: Securely log in and manage GitHub accounts.
*   **User and Repository Information Retrieval**: Fetch details about users and their repositories.
*   **Search Functionality**: Perform advanced searches for repositories, issues, and pull requests based on various criteria.
*   **Issue and Pull Request Management**: Create, view, and manage issues and pull requests (not explicitly demonstrated in this report but a core capability).
*   **API Interaction**: Directly interact with the GitHub API for more granular control and data access.

## Sample Data Fetched

### User Profile Information

Below is the user profile information fetched using `gh api user`:

```json
{
  "login": "nimikest-ui",
  "id": 224634966,
  "node_id": "U_kgDODWOoVg",
  "avatar_url": "https://avatars.githubusercontent.com/u/224634966?v=4",
  "gravatar_id": "",
  "url": "https://api.github.com/users/nimikest-ui",
  "html_url": "https://github.com/nimikest-ui",
  "followers_url": "https://api.github.com/users/nimikest-ui/followers",
  "following_url": "https://api.github.com/users/nimikest-ui/following{/other_user}",
  "gists_url": "https://api.github.com/users/nimikest-ui/gists{/gist_id}",
  "starred_url": "https://api.github.com/users/nimikest-ui/starred{/owner}{/repo}",
  "subscriptions_url": "https://api.github.com/users/nimikest-ui/subscriptions",
  "organizations_url": "https://api.github.com/users/nimikest-ui/orgs",
  "repos_url": "https://api.github.com/users/nimikest-ui/repos",
  "events_url": "https://api.github.com/users/nimikest-ui/events{/privacy}",
  "received_events_url": "https://api.github.com/users/nimikest-ui/received_events",
  "type": "User",
  "user_view_type": "public",
  "site_admin": false,
  "name": "Nimi Kest",
  "company": null,
  "blog": "",
  "location": null,
  "email": "nimikest@gmail.com",
  "hireable": null,
  "bio": null,
  "twitter_username": null,
  "notification_email": "nimikest@gmail.com",
  "public_repos": 1,
  "public_gists": 0,
  "followers": 0,
  "following": 0,
  "created_at": "2025-08-04T17:21:07Z",
  "updated_at": "2026-03-22T22:09:18Z"
}
```

### User Repositories

Here are the top 5 repositories associated with the user `nimikest-ui`:

| NAME | DESCRIPTION | INFO | UPDATED |
|---|---|---|---|
| nimikest-ui/Agent-Nimi | | public | about 5 days ago |

### Recent Issues Authored by User

A search for recent issues authored by the user (`gh search issues --author=@me --limit 5`) yielded no results, indicating no recent issues were created by this account.

### Popular Machine Learning Repositories

Below are 5 popular repositories related to 'machine-learning', sorted by stars, fetched using `gh search repos "topic:machine-learning" --limit 5 --sort stars`:

| NAME | DESCRIPTION | VISIBILITY | UPDATED |
|---|---|---|---|
| tensorflow/tensorflow | An Open Source Mac... | public | about 27 minutes ago |
| huggingface/transfor... | 🤗 Transformers: t... | public | about 5 minutes ago |
| f/prompts.chat | f.k.a. Awesome Cha... | public | about 5 minutes ago |
| pytorch/pytorch | Tensors and Dynami... | public | about 13 minutes ago |
| rasbt/LLMs-from-scratch | Implement a ChatGP... | public | about 4 minutes ago |
