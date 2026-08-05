def calculate_compatibility(p1, p2):
    """
    Computes a matching compatibility percentage between two UserProfiles (p1 and p2).
    Returns an integer percentage between 0 and 100.
    """
    if p1.id == p2.id:
        return 0

    score = 50  # Base compatibility score
    
    # 1. Neurotype Matching (Max 25%)
    # Overlapping neurotype labels (Autistic, ADHD, AuDHD, etc.)
    p1_neuro = set(p1.neurotype_labels or [])
    p2_neuro = set(p2.neurotype_labels or [])
    common_neuro = p1_neuro.intersection(p2_neuro)
    if common_neuro:
        score += 15
    elif p1.open_to_meet_neurodivergent and p2.is_neurodivergent:
        score += 10
    elif p2.open_to_meet_neurodivergent and p1.is_neurodivergent:
        score += 10

    # 2. Shared Qualities (Max 15%)
    p1_qual = set(p1.qualities or [])
    p2_qual = set(p2.qualities or [])
    common_qualities = p1_qual.intersection(p2_qual)
    score += len(common_qualities) * 5  # 5% per common quality (max 3, so max 15%)

    # 3. Shared Interests (Max 20%)
    p1_int = set(p1.interests or [])
    p2_int = set(p2.interests or [])
    common_interests = p1_int.intersection(p2_int)
    score += min(20, len(common_interests) * 5)  # 5% per interest, max 20%

    # 4. Recharge & Soothe Profiles (Max 15%)
    p1_recharge = set(p1.recharge_methods or [])
    p2_recharge = set(p2.recharge_methods or [])
    common_recharge = p1_recharge.intersection(p2_recharge)
    
    p1_soothe = set(p1.soothe_methods or [])
    p2_soothe = set(p2.soothe_methods or [])
    common_soothe = p1_soothe.intersection(p2_soothe)
    
    score += min(15, (len(common_recharge) + len(common_soothe)) * 5)

    # 5. Exhaustion Penalties (Min -20%)
    # If one user's interests or lifestyle habits trigger another user's sensory exhaustion
    p1_exhaust = set([t.lower() for t in (p1.exhaust_triggers or [])])
    p2_exhaust = set([t.lower() for t in (p2.exhaust_triggers or [])])
    
    # Check if p1's recharge or qualities cause discomfort to p2
    # e.g., if p2 is exhausted by "loud or unpredictable noises" and p1 has interests that are loud (like mechanical, engines, sports, etc.)
    p1_activity_tags = set([i.lower() for i in (p1.interests or [])])
    if p1.sport == 'Intense':
        p1_activity_tags.add('sport')
        p1_activity_tags.add('fast movements')
        
    p2_activity_tags = set([i.lower() for i in (p2.interests or [])])
    if p2.sport == 'Intense':
        p2_activity_tags.add('sport')
        p2_activity_tags.add('fast movements')

    # Apply penalty if p1 interests trigger p2's exhaust sensors
    for trigger in p2_exhaust:
        # Check simple substring/keyword match
        for tag in p1_activity_tags:
            if tag in trigger or trigger in tag:
                score -= 10
                break
                
    # Apply penalty if p2 interests trigger p1's exhaust sensors
    for trigger in p1_exhaust:
        for tag in p2_activity_tags:
            if tag in trigger or trigger in tag:
                score -= 10
                break

    # Cap between 0 and 100
    return max(0, min(100, score))
